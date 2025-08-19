import json, asyncio, logging, os, hashlib
from pathlib import Path
from app.bus import app, step_results, step_requests, report_topic, make_report, dlq_topic, ci_watch
from app.config import load_config
from app.state import finish_step, schedule_retry, list_ready_steps, now, upsert_step, task_all_ok, any_steps_remaining, set_meta, get_meta
from app.git_integration import prepare_repo_and_pr
from app.test_generator import generate_tests_from_story
import hashlib
from app.gitflow.materialize_impl import materialize_impl_to_staging 
from app.gitflow.materialize_tests import ensure_tests_for_task
from app.gitflow.prune_generated import run_prune
from app.gitflow.closed_loop import run_ci_closed_loop

cfg = load_config()
logger = logging.getLogger("agent-mvp.orchestrator")

_CHAIN = ["design@v1", "implement@v1", "test@v1", "review@v1"]
_BACKOFF = [int(x) for x in cfg["BACKOFF_S"].split(",") if x.strip()]
_MAX = cfg["MAX_ATTEMPTS"]

LOGFILE = Path(cfg["APP_DATA_DIR"]) / "reports.jsonl"
STORY_ROOT = Path(cfg.get("LOCAL_STORY_ROOT", "/workspaces/agent-mvp/meta/stories"))
STORY_POLL_S = int(cfg.get("STORY_POLL_S", "15"))
# this below is a file that stores the state of the orchestrator
STORY_STATE_PATH = Path(cfg["WORKSPACE_ROOT"]) / "meta" / "orchestrator_state.json"


def _append_report(obj: dict) -> None:
    LOGFILE.parent.mkdir(parents=True, exist_ok=True)
    with LOGFILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj) + "\n")

def _next_step(step_id: str) -> str | None:
    try:
        i = _CHAIN.index(step_id)
        return _CHAIN[i+1] if i+1 < len(_CHAIN) else None
    except ValueError:
        return None

# ── New: Story registry watcher configuration ──────────────────────────────────
STORY_ROOT = Path(cfg.get("LOCAL_STORY_ROOT", "/workspaces/agent-mvp/meta/stories"))
STORY_POLL_S = int(cfg.get("STORY_POLL_S", "15"))
AUTO_REPORT = cfg.get("ORCH_AUTO_REPORT", "1") == "1"
STORY_STATE_PATH = Path(cfg["WORKSPACE_ROOT"]) / "meta" / "orchestrator_state.json"

def _load_story_state() -> dict:
    if STORY_STATE_PATH.exists():
        try:
            return json.loads(STORY_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            STORY_STATE_PATH.rename(STORY_STATE_PATH.with_suffix(".corrupt.json"))
    # keyed by filename, not story_id
    return {"seen_story_files": {}, "version": 2}

def _save_story_state(state: dict) -> None:
    STORY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORY_STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STORY_STATE_PATH)

def _iter_story_files() -> list[Path]:
    if not STORY_ROOT.exists():
        return []
    return sorted([p for p in STORY_ROOT.glob("*.json") if p.is_file()])

def _safe_task_id_from_filename(fname: str) -> str:
    stem = Path(fname).stem
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in stem).strip("-") or "story"
    return f"seed-{safe}"

def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def _ensure_stage_exists_for_task(tid: str) -> None:
   
    stage_root = Path(cfg["LOCAL_GENERATED_ROOT"]) / tid
    stage_root.mkdir(parents=True, exist_ok=True)
    src_dir = stage_root / "src"
    # Ensure tests exist
    tests_dir = stage_root / "tests"
    if not tests_dir.exists() or not any(tests_dir.rglob("*.py")):
        ensure_tests_for_task(tid)
    # If tests/story_ref exist but src is empty, try materializing now
    if not src_dir.exists() or not any(src_dir.rglob("*")):
        from app.gitflow.materialize_impl import materialize_impl_to_staging
        materialize_impl_to_staging(tid, impl=None)
    if stage_root.exists():
        return

    # Try pointer
    refp = stage_root / "meta" / "story_ref.json"
    story_file = None
    if refp.exists():
        try:
            j = json.loads(refp.read_text(encoding="utf-8"))
            story_file = j.get("story_file")
        except Exception:
            pass

    # Fallback: if exactly one story file exists
    if not story_file:
        files = [p.name for p in Path(cfg["LOCAL_STORY_ROOT"]).glob("*.json")]
        if len(files) == 1:
            story_file = files[0]

    if not story_file:
        raise RuntimeError(f"Cannot infer story file for task {tid}; ensure meta/stories contains a single story or generate with --story-file.")

    generate_tests_from_story(task_id=tid, story_file=story_file)


@app.timer(interval=STORY_POLL_S)
async def story_watcher() -> None:
    try:
        state = _load_story_state()
        seen = state["seen_story_files"]
        for fp in _iter_story_files():
            name = fp.name
            if name in seen:
                continue

            try:
                tid = _safe_task_id_from_filename(name)
                # run generator with explicit story_file (filename)
                generate_tests_from_story(task_id=tid, story_file=name)

                seen[name] = {
                    "first_seen": now(),
                    "last_sha256": _sha256_bytes(fp.read_bytes()),
                    "task_id": tid,
                }
                _save_story_state(state)
                _append_report({"task_id": tid, "status": "story_seeded", "summary": f"Generated tests from {name}"})

                # OPTIONAL: kick off your first pipeline step
                # upsert_step(tid, _CHAIN[0])
                # await step_requests.send(key=tid.encode(), value={
                #   "task_id": tid, "step_id": _CHAIN[0], "attempt": 0, "inputs": {"story_file": name}
                # })

            except Exception as e:
                _append_report({"task_id": _safe_task_id_from_filename(name), "status": "error", "summary": f"Story seed failed for {name}: {e}"})
    except Exception as outer:
        logger.exception("story_watcher outer error: %s", outer)

# ── Existing publish logic ─────────────────────────────────────────────────────
async def _maybe_publish(tid: str) -> None:
    print("Checking if we should publish...")
    if get_meta(tid, "published", "0") == "1":
        return
    try:
        _ensure_stage_exists_for_task(tid)
    except Exception as e:
        # Make failure explicit and stop publish attempt
        _append_report({"task_id": tid, "status": "error",
                        "summary": f"Stage missing and could not auto-create: {e}"})
        return
    if task_all_ok(tid) and not any_steps_remaining(tid):
        data_dir = Path(cfg["APP_DATA_DIR"]) / tid
        design = json.loads((data_dir / "design@v1.json").read_text(encoding="utf-8"))
        impl   = json.loads((data_dir / "implement@v1.json").read_text(encoding="utf-8"))
        tests  = json.loads((data_dir / "test@v1.json").read_text(encoding="utf-8"))
        try:
            print(f"Preparing PR for task {tid} with design={design}, impl={impl}, tests={tests}")
            print(f"Preparing PR for task {tid} with calling prepare_repo_and_pr")
            pr_info = prepare_repo_and_pr(tid, design, impl, tests)
            try:
                # Run at most 1 fix round (tune as needed)
                loop = asyncio.get_running_loop()
                res = await loop.run_in_executor(
                    None,  # default executor
                    run_ci_closed_loop, tid, pr_info, design, impl
                )
                _append_report({"task_id": tid, "status": "ci_closed_loop", "summary": json.dumps(res)})
            except Exception as e:
                _append_report({"task_id": tid, "status": "warn", "summary": f"CI closed loop skipped: {e}"})

            pr_url = pr_info.get("pr_url")
            _append_report({"task_id": tid, "status": "pr_opened", "summary": f"PR: {pr_url}"})
            await report_topic.send(key=tid.encode(), value=make_report(tid, "pr", f"Opened PR: {pr_url}"))
            await ci_watch.send(key=tid.encode(), value={
                "task_id": tid,
                "repo": pr_info.get("repo"),
                "pr_number": pr_info.get("pr_number"),
                "head_sha": pr_info.get("head_sha"),
                "head_ref": pr_info.get("head_ref"),
            })
            set_meta(tid, "published", "1")
        except Exception as e:
            _append_report({"task_id": tid, "status": "error", "summary": f"PR error: {e}"})
            await report_topic.send(key=tid.encode(), value=make_report(tid, "error", f"PR error: {e}"))

# ── Existing pipeline orchestrator ─────────────────────────────────────────────
@app.agent(step_results)
async def orchestrator(stream):
    async for res in stream:
        tid = res["task_id"]; step_id = res["step_id"]
        status = res.get("status", ""); attempt = int(res.get("attempt", 1))

        if status == "ok":
            finish_step(tid, step_id, "ok", None)
            ready = list_ready_steps(tid)
            for nxt in ready:
                upsert_step(tid, nxt)
                _append_report({"task_id": tid, "status": "next", "stage": step_id, "summary": f"Enqueue {nxt}"})
                await step_requests.send(key=tid.encode(), value={
                    "task_id": tid, "step_id": nxt, "attempt": 0, "inputs": {}
                })
                if step_id == "implement@v1":
                    paths = materialize_impl_to_staging(tid, impl=None)
                    try:
                        written = ensure_tests_for_task(tid)
                        if written:
                            _append_report({"task_id": tid, "status": "tests_materialized",
                                            "summary": f"Wrote {len(written)} test file(s)"})
                    except Exception as e:
                        _append_report({"task_id": tid, "status": "warn",
                                        "summary": f"Could not materialize tests: {e}"})
                    if paths:
                        _append_report({"task_id": tid, "status": "impl_materialized",
                        "summary": f"Wrote {len(paths)} src files"})
                    
            await _maybe_publish(tid)
           
            # Example: keep newest 1 per story, prune both local & repo without a PR (or set --open-pr)
          

            # keep the most recent 2 tasks per story; prune both local staging and repo; no PR
       
            run_prune(keep_per_story=2, scope="both", open_pr=False, dry_run=False)
        else:
            if attempt < cfg["MAX_ATTEMPTS"]:
                backoff_s = int([int(x) for x in cfg["BACKOFF_S"].split(",") if x.strip()][min(attempt-1, len(cfg["BACKOFF_S"].split(","))-1)])
                schedule_retry(tid, step_id, not_before_ts=now() + float(backoff_s))
                _append_report({"task_id": tid, "status": "retry", "stage": step_id, "summary": f"Attempt {attempt+1} after {backoff_s}s"})
                await asyncio.sleep(backoff_s)
                upsert_step(tid, step_id)
                await step_requests.send(key=tid.encode(), value={
                    "task_id": tid, "step_id": step_id, "attempt": attempt, "inputs": {}
                })
            else:
                finish_step(tid, step_id, "fail", res.get("error"))
                _append_report({"task_id": tid, "status": "error", "stage": step_id, "summary": f"Failed after {attempt} attempts"})
                await dlq_topic.send(key=tid.encode(), value=res)
                await report_topic.send(key=tid.encode(), value=make_report(tid, "error", f"{step_id} failed after {attempt} attempts"))

if __name__ == "__main__":
    app.main()
