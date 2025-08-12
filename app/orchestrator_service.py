# app/orchestrator_service.py
import json, asyncio, logging
from pathlib import Path
from app.bus import app, step_results, step_requests, report_topic, make_report, dlq_topic
from app.config import load_config
from app.state import finish_step, schedule_retry, enqueue_step, now   # ← add enqueue_step, now

cfg = load_config()
logger = logging.getLogger("agent-mvp.orchestrator")

_CHAIN = ["design@v1", "implement@v1", "test@v1", "review@v1"]
_BACKOFF = [int(x) for x in cfg["BACKOFF_S"].split(",") if x.strip()]
_MAX = cfg["MAX_ATTEMPTS"]



cfg = load_config()
LOGFILE = Path(cfg["DATA_DIR"]) / "reports.jsonl"
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

@app.agent(step_results)
async def orchestrator(stream):
    async for res in stream:
        tid = res["task_id"]; step_id = res["step_id"]
        status = res.get("status", "")
        attempt = int(res.get("attempt", 1))

        if status == "ok":
            # ...inside orchestrator(), when status == "ok":
            finish_step(tid, step_id, "ok", None)
            nxt = _next_step(step_id)
            if nxt:
                enqueue_step(tid, nxt)
                _append_report({"task_id": tid, "status": "next", "stage": step_id, "summary": f"Enqueue {nxt}"})
                await step_requests.send(key=tid.encode(), value={
                    "task_id": tid, "step_id": nxt, "attempt": 0, "inputs": {}
                })
            else:
                # REVIEW completed → open PR with generated code + tests
                try:
                    data_dir = Path(cfg["DATA_DIR"]) / tid
                    design = json.loads((data_dir / "design@v1.json").read_text(encoding="utf-8"))
                    impl   = json.loads((data_dir / "implement@v1.json").read_text(encoding="utf-8"))
                    tests  = json.loads((data_dir / "test@v1.json").read_text(encoding="utf-8"))

                    pr_info = prepare_repo_and_pr(tid, design, impl, tests)
                    pr_url = pr_info.get("pr_url")
                    _append_report({"task_id": tid, "status": "pr_opened", "summary": f"PR: {pr_url}"})
                    await report_topic.send(key=tid.encode(), value=make_report(tid, "pr", f"Opened PR: {pr_url}"))

                    # Enqueue CI monitor
                    await ci_watch.send(key=tid.encode(), value={
                        "task_id": tid,
                        "repo": pr_info.get("repo"),
                        "pr_number": pr_info.get("pr_number"),
                        "head_sha": pr_info.get("head_sha"),
                        "head_ref": pr_info.get("head_ref"),
                    })
                except Exception as e:
                    _append_report({"task_id": tid, "status": "error", "summary": f"PR error: {e}"})
                    await report_topic.send(key=tid.encode(), value=make_report(tid, "error", f"PR error: {e}"))

                # Final done marker (independent of CI result)
                _append_report({"task_id": tid, "status": "done", "summary": f"Task {tid} completed"})
                await report_topic.send(key=tid.encode(), value=make_report(tid, "done", f"Task {tid} completed"))

        else:
            # failure path with retry/backoff
            if attempt < _MAX:
                backoff_s = _BACKOFF[min(attempt-1, len(_BACKOFF)-1)]
                schedule_retry(tid, step_id, not_before_ts=now() + float(backoff_s))
                _append_report({"task_id": tid, "status": "retry", "stage": step_id,
                                "summary": f"Attempt {attempt+1} after {backoff_s}s"})
                await asyncio.sleep(backoff_s)   # simple timer; replace with delayed queue later
                # Requeue same step and make it claimable again
                enqueue_step(tid, step_id)      # ← critical for retries
                await step_requests.send(key=tid.encode(), value={
                    "task_id": tid, "step_id": step_id, "attempt": attempt, "inputs": {}
                })
            else:
                finish_step(tid, step_id, "fail", res.get("error"))
                _append_report({"task_id": tid, "status": "error", "stage": step_id,
                                "summary": f"Failed after {attempt} attempts"})
                await dlq_topic.send(key=tid.encode(), value=res)
                await report_topic.send(key=tid.encode(),
                    value=make_report(tid, "error",
                    f"{step_id} failed after {attempt} attempts"))
                
if __name__ == "__main__":
    app.main()