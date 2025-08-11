import os, json, time, uuid
from pathlib import Path
from typing import Any, Dict

from agents import Runner
from app.bus import app, task_topic, report_topic, make_report
from app.agents import make_architect_agent, make_implementer_agent, make_tester_agent, make_reviewer_agent
from app.config import load_config
from app.state_json import upsert_task, upsert_step, append_artifact
from app.models import step_result

cfg = load_config()
DATA_DIR = Path(cfg["DATA_DIR"]); DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGFILE = DATA_DIR / "reports.jsonl"

def _to_jsonable(obj: Any) -> Any:
    try:
        from pydantic import BaseModel
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

async def _run_step(agent, task_id: str, step_id: str, name: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
    lease_id = str(uuid.uuid4())
    upsert_step(task_id, step_id, status="running", attempt=1, lease_id=lease_id, started_at=time.time())
    res = await Runner.run(agent, inputs.get("prompt", ""), context=inputs)
    output = _to_jsonable(res.final_output)
    artifacts = {f"{step_id}.json": output}
    sr = step_result(task_id, step_id, "ok", artifacts, f"{name} completed", metrics={})
    step_path = DATA_DIR / task_id / f"{step_id}.json"
    _write_json(step_path, output)
    append_artifact(task_id, step_id, f"{step_id}.json", str(step_path))
    upsert_step(task_id, step_id, status="ok", lease_id=lease_id, finished_at=time.time())
    return sr

def _summarize_done(task_id: str) -> str:
    return f"Task {task_id} completed; artifacts in {DATA_DIR/task_id} and state in {DATA_DIR/'state.json'}"

@app.agent(task_topic)
async def handle_tasks(stream):
    async for task in stream:
        tid = task.get("task_id", str(uuid.uuid4()))
        prompt = task.get("prompt", "").strip() or "Do nothing"
        try:
            upsert_task(tid, {"prompt": prompt})
            arch = make_architect_agent()
            await _run_step(arch, tid, "design@v1", "Design", {"prompt": prompt})
            impl = make_implementer_agent()
            await _run_step(impl, tid, "implement@v1", "Implement", {"prompt": prompt})
            tester = make_tester_agent()
            await _run_step(tester, tid, "test@v1", "Test", {"prompt": prompt})
            reviewer = make_reviewer_agent()
            await _run_step(reviewer, tid, "review@v1", "Review", {"prompt": prompt})
            summary = _summarize_done(tid)
            await report_topic.send(key=tid.encode(), value=make_report(tid, "done", summary))
            with LOGFILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"task_id": tid, "status": "done", "summary": summary}) + "\n")
        except Exception as e:
            err = f"error: {e}"
            await report_topic.send(key=tid.encode(), value=make_report(tid, "error", err))
            with LOGFILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"task_id": tid, "status": "error", "summary": err}) + "\n")
