# app/orchestrator_service.py
import json, asyncio, logging
from app.bus import app, step_results, step_requests, report_topic, make_report, dlq_topic
from app.config import load_config
from app.state import finish_step, schedule_retry

cfg = load_config()
logger = logging.getLogger("agent-mvp.orchestrator")

_CHAIN = ["design@v1", "implement@v1", "test@v1", "review@v1"]
_BACKOFF = [int(x) for x in cfg["BACKOFF_S"].split(",") if x.strip()]
_MAX = cfg["MAX_ATTEMPTS"]

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
            nxt = _next_step(step_id)
            if nxt:
                await step_requests.send(key=tid.encode(), value={
                    "task_id": tid, "step_id": nxt, "attempt": 0, "inputs": {}
                })
            else:
                # task done
                await report_topic.send(key=tid.encode(), value=make_report(tid, "done", f"Task {tid} completed"))
        else:
            # failure path with retry/backoff
            if attempt < _MAX:
                backoff_s = _BACKOFF[min(attempt-1, len(_BACKOFF)-1)]
                schedule_retry(tid, step_id, not_before_ts=float(backoff_s))
                logger.warning("Scheduling retry: task=%s step=%s attempt=%s backoff=%ss", tid, step_id, attempt+1, backoff_s)
                await asyncio.sleep(backoff_s)   # simple timer; replace w/ delayed-queue later
                await step_requests.send(key=tid.encode(), value={
                    "task_id": tid, "step_id": step_id, "attempt": attempt, "inputs": {}
                })
            else:
                finish_step(tid, step_id, "fail", res.get("error"))
                await dlq_topic.send(key=tid.encode(), value=res)
                await report_topic.send(key=tid.encode(), value=make_report(tid, "error", f"{step_id} failed after {attempt} attempts"))

if __name__ == "__main__":
    app.main()
