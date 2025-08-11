# app/worker.py
import os, json
from typing import Any, Tuple
from agents import Runner
from app.bus import app, task_topic, report_topic
from app.agents import make_triage_agent
from app.config import load_config
from pathlib import Path

cfg = load_config()
Path(cfg["DATA_DIR"]).mkdir(parents=True, exist_ok=True)
LOGFILE = os.path.join(cfg["DATA_DIR"], "reports.jsonl")

def _normalize_summary(obj: Any) -> Tuple[str, Any | None]:
    """Return (summary_text, summary_json). `summary_text` is always a string."""
    try:
        from pydantic import BaseModel as _BM  # type: ignore
    except Exception:
        _BM = tuple()  # fallback
    if isinstance(obj, str):
        return obj, None
    if _BM and isinstance(obj, _BM):
        data = obj.model_dump()
        return json.dumps(data, ensure_ascii=False), data
    if isinstance(obj, (dict, list)):
        return json.dumps(obj, ensure_ascii=False), obj
    return str(obj), None

@app.agent(task_topic)
async def handle_tasks(stream):
    async for task in stream:  # dict due to value_serializer='json'
        try:
            triage = make_triage_agent()
            result = await Runner.run(triage, task["prompt"])

            summary_text, summary_json = _normalize_summary(result.final_output)
            report = {
                "task_id": task["task_id"],
                "status": "done",
                "summary": summary_text,
            }
            if summary_json is not None:
                report["summary_json"] = summary_json  # optional structured details

            # emit to report topic
            await report_topic.send(key=task["task_id"].encode(), value=report)

            # append to JSONL for UI
            with open(LOGFILE, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "task_id": task["task_id"],
                    "status": "done",
                    "summary": summary_text
                }) + "\n")

        except Exception as e:
            err = f"error: {e}"
            tid = task.get("task_id", "?") if isinstance(task, dict) else "?"
            await report_topic.send(key=str(tid).encode(),
                                    value={"task_id": tid, "status": "error", "summary": err})
            with open(LOGFILE, "a", encoding="utf-8") as f:
                f.write(json.dumps({"task_id": tid, "status": "error", "summary": err}) + "\n")

if __name__ == "__main__":
    app.main()