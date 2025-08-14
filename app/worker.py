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
DATA_DIR = Path(cfg["APP_DATA_DIR"]); DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGFILE = Path(DATA_DIR) / "reports.jsonl"; LOGFILE.touch(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("agent-mvp.worker")
logger.info("Worker starting; brokers=%s data_dir=%s step_requests=%s",
            cfg["REDPANDA_BROKERS"], cfg["APP_DATA_DIR"], cfg["STEP_REQUESTS_TOPIC"])

def _read_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _get_original_prompt_from_reports(task_id: str) -> str | None:
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

def _append_report(obj: Dict[str, Any]) -> None:
    with LOGFILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

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
    async for req in stream:
        tid = req["task_id"]; step_id = req["step_id"]
        lease = claim_step(tid, step_id, cfg["LEASE_TTL_S"])
        if not lease:
            logger.info("Skip (not claimable): task=%s step=%s", tid, step_id)
            continue
        lease_id, attempt = lease
        logger.info("Running: task=%s step=%s attempt=%s lease=%s", tid, step_id, attempt, lease_id)

        # ---- rehydrate context if missing ----
        inputs = req.get("inputs") or {}
        prompt = (inputs.get("prompt") or "").strip()
        if not prompt:
            prompt = _get_original_prompt_from_reports(tid) or ""

        # Load prior artifacts on demand
        base = DATA_DIR / tid
        if step_id in ("implement@v1", "test@v1", "review@v1") and "design" not in inputs:
            d = _read_json(base / "design@v1.json")
            if d is not None:
                inputs["design"] = d
        if step_id in ("test@v1", "review@v1") and "impl" not in inputs:
            im = _read_json(base / "implement@v1.json")
            if im is not None:
                inputs["impl"] = im
        if step_id == "review@v1" and "tests" not in inputs:
            t = _read_json(base / "test@v1.json")
            if t is not None:
                inputs["tests"] = t
        # ----------------------------------
        agent = _agent_for(step_id)
        try:
            res = await Runner.run(agent, prompt, context=inputs)
            out = _to_jsonable(res.final_output)

            # Persist artifacts (versioned attempt + current)
            path = _write_artifact(tid, step_id, attempt, out)
            try:
                size = path.stat().st_size
            except Exception:
                size = 0

            # Register artifact in SQLite
            record_artifact(tid, step_id, attempt, f"{step_id}.json", str(path), size)

            # Tell the orchestrator we finished this step successfully
            await step_results.send(key=tid.encode(), value={
                "task_id": tid,
                "step_id": step_id,
                "status": "ok",
                "attempt": attempt,
                "ts": now(),
            })
            logger.info("Emitted step_results OK: task=%s step=%s attempt=%s", tid, step_id, attempt)

            # Optional: mirror to reports.jsonl for the UI
            _append_report({"task_id": tid, "status": "stage_done", "stage": step_id,
                            "summary": f"{step_id} completed"})

        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            logger.exception("Step failed: task=%s step=%s attempt=%s", tid, step_id, attempt)

            # Notify orchestrator of failure (it will schedule retries / DLQ)
            await step_results.send(key=tid.encode(), value={
                "task_id": tid,
                "step_id": step_id,
                "status": "fail",
                "attempt": attempt,
                "error": err,
                "ts": now(),
            })

            # Optional: mirror failure to reports.jsonl
            _append_report({"task_id": tid, "status": "error", "stage": step_id, "summary": err})


if __name__ == "__main__":
    app.main()