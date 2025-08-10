import os, json
from agents import Runner
from app.bus import app, task_topic, report_topic, make_report
from app.agents import make_triage_agent
from app.config import load_config
from pathlib import Path

cfg = load_config()
Path(cfg["DATA_DIR"]).mkdir(parents=True, exist_ok=True)
LOGFILE = os.path.join(cfg["DATA_DIR"], "reports.jsonl")

@app.agent(task_topic)
async def handle_tasks(stream):
    async for task in stream:
        try:
            triage = make_triage_agent()
            result = await Runner.run(triage, task["prompt"])
            final_text = result.final_output
            await report_topic.send(key=task["task_id"].encode(), value=make_report(task["task_id"], "done", final_text))
            with open(LOGFILE, "a", encoding="utf-8") as f:
                f.write(json.dumps({"task_id": task["task_id"], "status": "done", "summary": final_text}) + "\n")
        except Exception as e:
            err = f"error: {e}"
            tid = task.get("task_id", "?") if isinstance(task, dict) else "?"
            await report_topic.send(key=str(tid).encode(), value=make_report(tid, "error", err))
            with open(LOGFILE, "a", encoding="utf-8") as f:
                f.write(json.dumps({"task_id": tid, "status": "error", "summary": err}) + "\n")

if __name__ == "__main__":
    app.main()
