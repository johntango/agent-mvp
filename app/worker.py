import os, json, time, uuid, logging
from pathlib import Path
from typing import Any, Dict, Tuple

from agents import Runner
from app.bus import app, task_topic, report_topic, make_report
from app.agents import (
    make_architect_agent, make_implementer_agent,
    make_tester_agent, make_reviewer_agent
)
from app.config import load_config
from app.state_json import upsert_task, upsert_step, append_artifact

# ---------- Setup ----------

cfg = load_config()
DATA_DIR = Path(cfg["DATA_DIR"])
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGFILE = DATA_DIR / "reports.jsonl"
LOGFILE.parent.mkdir(parents=True, exist_ok=True)
LOGFILE.touch(exist_ok=True)

logger = logging.getLogger("agent-mvp.worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger.info(
    "Worker starting; brokers=%s data_dir=%s task_topic=%s report_topic=%s",
    cfg.get("REDPANDA_BROKERS"), cfg.get("DATA_DIR"), cfg.get("TASK_TOPIC"), cfg.get("REPORT_TOPIC")
)

# ---------- Helpers ----------

def _to_jsonable(obj: Any) -> Any:
    """Coerce Pydantic and other objects to JSON-serializable values."""
    try:
        from pydantic import BaseModel  # type: ignore
        if isinstance(obj, BaseModel):
            return obj.model_dump()
    except Exception:
        pass
    if isinstance(obj, (dict, list, str, int, float, bool)) or obj is None:
        return obj
    return str(obj)

def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(_to_jsonable(obj), f, ensure_ascii=False, indent=2)

def _append_report_line(obj: Dict[str, Any]) -> None:
    with LOGFILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

async def _run_step(agent, task_id: str, step_id: str, name: str, inputs: Dict[str, Any]) -> Any:
    """Run a single agent step, persist artifact, and update state.json."""
    lease_id = str(uuid.uuid4())
    t0 = time.time()
    upsert_step(task_id, step_id, status="running", attempt=1, lease_id=lease_id, started_at=t0)
    logger.info("Step start: task_id=%s step_id=%s", task_id, step_id)

    res = await Runner.run(agent, inputs.get("prompt", ""), context=inputs)
    out = _to_jsonable(res.final_output)

    # Persist artifact to ./data/<task_id>/<step_id>.json and register in state.json
    step_path = DATA_DIR / task_id / f"{step_id}.json"
    _write_json(step_path, out)
    append_artifact(task_id, step_id, f"{step_id}.json", str(step_path))

    upsert_step(task_id, step_id, status="ok", lease_id=lease_id, finished_at=time.time())
    logger.info("Step done: task_id=%s step_id=%s wrote=%s", task_id, step_id, step_path)

    # Append a progress line for the UI/debug
    _append_report_line({
        "task_id": task_id,
        "status": "stage_done",
        "stage": step_id,
        "summary": f"{name} completed",
    })
    return out

# ---------- Faust stream processor ----------

@app.agent(task_topic)
async def handle_tasks(stream):
    async for task in stream:  # value_serializer='json' -> dict
        tid = task.get("task_id", str(uuid.uuid4()))
        prompt = (task.get("prompt") or "").strip()
        logger.info("Received task_id=%s prompt=%r", tid, prompt)

        # Immediate "received" marker so you see activity quickly
        _append_report_line({"task_id": tid, "status": "received", "summary": prompt})

        try:
            # Record/initialize task spec in JSON state
            upsert_task(tid, {"prompt": prompt})

            # 1) Design
            arch = make_architect_agent()
            design_out = await _run_step(arch, tid, "design@v1", "Design", {"prompt": prompt})

            # 2) Implement
            impl = make_implementer_agent()
            impl_out = await _run_step(impl, tid, "implement@v1", "Implement",
                                       {"prompt": prompt, "design": design_out})

            # 3) Test
            tester = make_tester_agent()
            test_out = await _run_step(tester, tid, "test@v1", "Test",
                                       {"prompt": prompt, "design": design_out, "impl": impl_out})

            # 4) Review
            reviewer = make_reviewer_agent()
            rev_out = await _run_step(reviewer, tid, "review@v1", "Review",
                                      {"prompt": prompt, "design": design_out, "impl": impl_out, "tests": test_out})

            # Final report
            summary = f"Task {tid} completed; artifacts in {DATA_DIR / tid} and state in {DATA_DIR / 'state.json'}"
            await report_topic.send(key=tid.encode(), value=make_report(tid, "done", summary))
            _append_report_line({"task_id": tid, "status": "done", "summary": summary})

        except Exception as e:
            err = f"error: {e}"
            logger.exception("Task failed: task_id=%s", tid)
            await report_topic.send(key=tid.encode(), value=make_report(tid, "error", err))
            _append_report_line({"task_id": tid, "status": "error", "summary": err})
