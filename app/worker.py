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
REPORTS_PATH = Path(cfg["REPORTS_PATH"])
log = logging.getLogger(__name__)
cfg = load_config()
REPO_ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = Path(cfg["DATA_DIR"])
DATA_DIR.mkdir(parents=True, exist_ok=True)

LOGFILE = DATA_DIR / "reports.jsonl"
LOGFILE.parent.mkdir(parents=True, exist_ok=True)
LOGFILE.touch(exist_ok=True)

REPORTS_PATH = DATA_DIR / "reports.jsonl"


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

@app.agent(task_topic)
async def handle_tasks(stream):
    async for task in stream:  # value_serializer='json' => dict
        tid = task.get("task_id", str(uuid.uuid4()))
        prompt = (task.get("prompt") or "").strip()
        logger.info("Received task_id=%s prompt=%r", tid, prompt)
        _append_report({"task_id": tid, "status": "received", "summary": prompt})

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