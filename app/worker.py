# app/worker.py
import os, json, time, uuid, logging
from pathlib import Path
from typing import Any, Dict

from agents import Runner
from app.bus import app, task_topic, report_topic, make_report
from app.agents import (
    make_architect_agent, make_implementer_agent,
    make_tester_agent, make_reviewer_agent
)
from app.config import load_config

cfg = load_config()

DATA_DIR = Path(cfg["DATA_DIR"])
DATA_DIR.mkdir(parents=True, exist_ok=True)

LOGFILE = DATA_DIR / "reports.jsonl"
LOGFILE.parent.mkdir(parents=True, exist_ok=True)
LOGFILE.touch(exist_ok=True)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("agent-mvp.worker")
logger.info("Worker starting; brokers=%s data_dir=%s task_topic=%s report_topic=%s",
            cfg.get("REDPANDA_BROKERS"), cfg.get("DATA_DIR"), cfg.get("TASK_TOPIC"), cfg.get("REPORT_TOPIC"))

def _to_jsonable(obj: Any) -> Any:
    try:
        from pydantic import BaseModel  # type: ignore
        if isinstance(obj, BaseModel):
            return obj.model_dump()
    except Exception:
        pass
    if isinstance(obj, (dict, list, str, int, float, bool)) or obj is None:
        return obj
    return str(obj)

def _write_artifact(task_id: str, step_id: str, value: Any) -> Path:
    path = DATA_DIR / task_id / f"{step_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(_to_jsonable(value), f, ensure_ascii=False, indent=2)
    return path

def _append_report(obj: Dict[str, Any]) -> None:
    with LOGFILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def append_report_line(report_dict: dict) -> None:
    line = json.dumps(report_dict, ensure_ascii=False)
    with REPORTS_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

def _read_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _get_original_prompt_from_reports(task_id: str) -> str | None:
    # first 'received' line for this task contains the original prompt
    try:
        with (DATA_DIR / "reports.jsonl").open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("task_id") == task_id and obj.get("status") == "received":
                    return obj.get("summary")
    except FileNotFoundError:
        pass
    return None

def _artifact_path(task_id: str, step_id: str, attempt: int | None = None) -> Path:
    base = DATA_DIR / task_id
    if attempt is None:
        return base / f"{step_id}.json"
    return base / f"{step_id}.attempt{attempt}.json"

def _next_attempt_index(task_id: str, step_id: str) -> int:
    base = DATA_DIR / task_id
    if not base.exists():
        return 1
    n = 1
    for p in base.glob(f"{step_id}.attempt*.json"):
        try:
            idx = int(p.stem.split(".attempt")[-1])
            n = max(n, idx + 1)
        except Exception:
            pass
    return n

@app.agent(task_topic)
async def handle_tasks(stream):
    async for task in stream:  # value_serializer='json' => dict
        tid = task.get("task_id", str(uuid.uuid4()))
        prompt = (task.get("prompt") or "").strip()
        logger.info("Received task_id=%s prompt=%r", tid, prompt)
        _append_report({"task_id": tid, "status": "received", "summary": prompt})
        action = (task.get("action") or "").strip()
        if action == "replay_step":
            step_id = task.get("step_id")
            reason = (task.get("reason") or "").strip()
            logger.info("Replay requested: task_id=%s step_id=%s reason=%r", tid, step_id, reason)
            _append_report({"task_id": tid, "status": "replay_request", "stage": step_id, "summary": f"Replay requested: {reason}"})

            # reconstruct minimal context
            prompt = _get_original_prompt_from_reports(tid) or ""
            design_out = _read_json(_artifact_path(tid, "design@v1"))
            impl_out   = _read_json(_artifact_path(tid, "implement@v1"))
            test_out   = _read_json(_artifact_path(tid, "test@v1"))

            # choose agent + inputs
            if step_id == "design@v1":
                agent = make_architect_agent()
                ctx = {"prompt": prompt}
                name = "Design"
            elif step_id == "implement@v1":
                agent = make_implementer_agent()
                if design_out is None:
                    raise RuntimeError("Cannot replay implement@v1: missing design@v1 artifact")
                ctx = {"prompt": prompt, "design": design_out}
                name = "Implement"
            elif step_id == "test@v1":
                agent = make_tester_agent()
                if design_out is None or impl_out is None:
                    raise RuntimeError("Cannot replay test@v1: missing design/implement artifacts")
                ctx = {"prompt": prompt, "design": design_out, "impl": impl_out}
                name = "Test"
            elif step_id == "review@v1":
                agent = make_reviewer_agent()
                if design_out is None or impl_out is None or test_out is None:
                    raise RuntimeError("Cannot replay review@v1: missing prior artifacts")
                ctx = {"prompt": prompt, "design": design_out, "impl": impl_out, "tests": test_out}
                name = "Review"
            else:
                raise RuntimeError(f"Unknown step_id: {step_id}")

            # run and version the artifact
            r = await Runner.run(agent, prompt, context=ctx)
            out = _to_jsonable(r.final_output)

            attempt = _next_attempt_index(tid, step_id)
            # keep a versioned copy and overwrite the canonical
            p_ver = _artifact_path(tid, step_id, attempt)
            p_cur = _artifact_path(tid, step_id, None)
            p_ver.parent.mkdir(parents=True, exist_ok=True)
            with p_ver.open("w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
            with p_cur.open("w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)

            _append_report({"task_id": tid, "status": "stage_done", "stage": step_id, "summary": f"{name} replayed (attempt {attempt})"})
            await report_topic.send(key=tid.encode(), value=make_report(tid, "replayed", f"{name} replayed (attempt {attempt})"))
            logger.info("Replay done: task_id=%s step_id=%s attempt=%s", tid, step_id, attempt)
            # continue (do not run the normal full pipeline)
            continue
        try:
            # 1) Design
            arch = make_architect_agent()
            r_arch = await Runner.run(arch, prompt, context={"prompt": prompt})
            design_out = r_arch.final_output
            _write_artifact(tid, "design@v1", design_out)
            _append_report({"task_id": tid, "status": "stage_done", "stage": "design@v1", "summary": "Design completed"})

            # 2) Implement
            impl = make_implementer_agent()
            r_impl = await Runner.run(impl, prompt, context={"prompt": prompt, "design": design_out})
            impl_out = r_impl.final_output
            _write_artifact(tid, "implement@v1", impl_out)
            _append_report({"task_id": tid, "status": "stage_done", "stage": "implement@v1", "summary": "Implement completed"})

            # 3) Test
            tester = make_tester_agent()
            r_test = await Runner.run(tester, prompt, context={"prompt": prompt, "design": design_out, "impl": impl_out})
            test_out = r_test.final_output
            _write_artifact(tid, "test@v1", test_out)
            _append_report({"task_id": tid, "status": "stage_done", "stage": "test@v1", "summary": "Test completed"})

            # 4) Review
            reviewer = make_reviewer_agent()
            r_rev = await Runner.run(reviewer, prompt, context={"prompt": prompt, "design": design_out, "impl": impl_out, "tests": test_out})
            rev_out = r_rev.final_output
            _write_artifact(tid, "review@v1", rev_out)
            _append_report({"task_id": tid, "status": "stage_done", "stage": "review@v1", "summary": "Review completed"})

            summary = f"Task {tid} completed; artifacts in {DATA_DIR / tid}"
            await report_topic.send(key=tid.encode(), value=make_report(tid, "done", summary))
            _append_report({"task_id": tid, "status": "done", "summary": summary})
            logger.info("Task done: task_id=%s", tid)

        except Exception as e:
            err = f"error: {e}"
            logger.exception("Task failed: task_id=%s", tid)
            await report_topic.send(key=tid.encode(), value=make_report(tid, "error", err))
            _append_report({"task_id": tid, "status": "error", "summary": err})

if __name__ == "__main__":
    app.main()