# app/planner_service.py
import json, uuid, logging
from pathlib import Path
from app.bus import app, task_topic, step_requests, make_report, report_topic
from app.config import load_config
from app.state import init_task, enqueue_step

cfg = load_config()
DATA_DIR = Path(cfg["DATA_DIR"]); DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGFILE = DATA_DIR / "reports.jsonl"
logger = logging.getLogger("agent-mvp.planner")

def _append_report(obj: dict) -> None:
    LOGFILE.parent.mkdir(parents=True, exist_ok=True)
    with LOGFILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

@app.agent(task_topic)
async def planner(stream):
    async for msg in stream:
        # Two shapes: new task OR replay command
        action = (msg.get("action") or "").strip()
        tid = msg.get("task_id") or str(uuid.uuid4())

        if not action:
            prompt = (msg.get("prompt") or "").strip()
            init_task(tid, prompt)
            _append_report({"task_id": tid, "status": "received", "summary": prompt})
            await report_topic.send(key=tid.encode(), value=make_report(tid, "received", prompt))

            # enqueue first step
            enqueue_step(tid, "design@v1")
            await step_requests.send(key=tid.encode(), value={
                "task_id": tid, "step_id": "design@v1", "attempt": 0, "inputs": {"prompt": prompt}
            })
        elif action == "replay_step":
            step_id = msg["step_id"]
            reason = (msg.get("reason") or "").strip()
            _append_report({"task_id": tid, "status": "replay_request", "stage": step_id, "summary": reason})
            enqueue_step(tid, step_id)
            await step_requests.send(key=tid.encode(), value={
                "task_id": tid, "step_id": step_id, "attempt": 0, "inputs": {}  # worker reconstructs context
            })
        else:
            _append_report({"task_id": tid, "status": "error", "summary": f"unknown action: {action}"})

if __name__ == "__main__":
    app.main()
