# app/worker.py
import os, json, time, uuid, logging
from pathlib import Path
from typing import Any, Dict

from agents import Runner
from app.bus import app, step_requests, step_results
from app.agents import (
    make_architect_agent, make_implementer_agent,
    make_tester_agent, make_reviewer_agent
)
from app.config import load_config
from app.state import claim_step, finish_step, record_artifact, now

cfg = load_config()
DATA_DIR = Path(cfg["DATA_DIR"]); DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGFILE = DATA_DIR / "reports.jsonl"; LOGFILE.touch(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("agent-mvp.worker")
logger.info("Worker starting; brokers=%s data_dir=%s step_requests=%s",
            cfg["REDPANDA_BROKERS"], cfg["DATA_DIR"], cfg["STEP_REQUESTS_TOPIC"])

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

def _write_artifact(task_id: str, step_id: str, attempt: int, value: Any) -> Path:
    path = DATA_DIR / task_id / f"{step_id}.attempt{attempt}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(_to_jsonable(value), f, ensure_ascii=False, indent=2)
    # also update current
    cur = DATA_DIR / task_id / f"{step_id}.json"
    with cur.open("w", encoding="utf-8") as f:
        json.dump(_to_jsonable(value), f, ensure_ascii=False, indent=2)
    return path

def _agent_for(step_id: str):
    return {
        "design@v1": make_architect_agent,
        "implement@v1": make_implementer_agent,
        "test@v1": make_tester_agent,
        "review@v1": make_reviewer_agent,
    }[step_id]()

@app.agent(step_requests)
async def handle_steps(stream):
    async for req in stream:  # dict
        tid = req["task_id"]; step_id = req["step_id"]
        lease = claim_step(tid, step_id, cfg["LEASE_TTL_S"])
        if not lease:
            logger.info("Skip (not claimable): task=%s step=%s", tid, step_id)
            continue
        lease_id, attempt = lease
        logger.info("Running: task=%s step=%s attempt=%s lease=%s", tid, step_id, attempt, lease_id)

        # Reconstruct minimal inputs: planner may have sent prompt in inputs of the first step; later steps can run without
        inputs = req.get("inputs") or {}
        prompt = (inputs.get("prompt") or "").strip()

        try:
            agent = _agent_for(step_id)
            res = await Runner.run(agent, prompt, context=inputs)
            out = _to_jsonable(res.final_output)

            # persist artifacts
            path = _write_artifact(tid, step_id, attempt, out)
            try:
                size = path.stat().st_size
            except Exception:
                size = 0
            record_artifact(tid, step_id, attempt, f"{step_id}.json", str(path), size)

            finish_step(tid, step_id, "ok", None)
            await step_results.send(key=tid.encode(), value={
                "task_id": tid,
                "step_id": step_id,
                "status": "ok",
                "attempt": attempt,
                "ts": now()
            })
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            finish_step(tid, step_id, "fail", err)
            await step_results.send(key=tid.encode(), value={
                "task_id": tid,
                "step_id": step_id,
                "status": "fail",
                "attempt": attempt,
                "error": err,
                "ts": now()
            })

if __name__ == "__main__":
    app.main()
