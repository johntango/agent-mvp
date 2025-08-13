import json, asyncio, logging, os
from pathlib import Path
from app.bus import app, step_results, step_requests, report_topic, make_report, dlq_topic
from app.config import load_config
from app.state import finish_step, schedule_retry, list_ready_steps, now, upsert_step

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
            finish_step(tid, step_id, "ok", None)

            # Promote all steps that are now ready
            ready = list_ready_steps(tid)
            for nxt in ready:
                # Ensure step row exists and is in 'queued' (safe idempotent)
                upsert_step(tid, nxt)
                _append_report({"task_id": tid, "status": "next", "stage": step_id, "summary": f"Enqueue {nxt}"})
                await step_requests.send(key=tid.encode(), value={
                    "task_id": tid, "step_id": nxt, "attempt": 0, "inputs": {}  # worker rehydrates
                })

            # If nothing else is ready and no more queued steps exist, you may mark done
            # (Your existing PR/CI logic can remain when final 'review@v1' completes.)
            if not ready and step_id == "review@v1":
                _append_report({"task_id": tid, "status": "done", "summary": f"Task {tid} completed"})
                await report_topic.send(key=tid.encode(), value=make_report(tid, "done", f"Task {tid} completed"))

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