# app/planner_service.py
import json, uuid, logging
from pathlib import Path
from app.bus import app, task_topic, step_requests, make_report, report_topic
from app.config import load_config
from app.state import init_task, save_plan, upsert_step, add_dependency, list_ready_steps
from app.plan_model import Plan, validate_plan, STEP_CATALOG
from app.agents import make_planner_agent
from agents import Runner  # your OpenAI Agents SDK runner

cfg = load_config()
DATA_DIR = Path(cfg["DATA_DIR"]); DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGFILE = DATA_DIR / "reports.jsonl"
logger = logging.getLogger("agent-mvp.planner")

def _append_report(obj: dict) -> None:
    LOGFILE.parent.mkdir(parents=True, exist_ok=True)
    with LOGFILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

async def _make_plan(task_id: str, prompt: str) -> Plan:
    planner = make_planner_agent()
    res = await Runner.run(planner, prompt, context={"task_id": task_id})
    plan = res.final_output  # Pydantic Plan
    return validate_plan(plan)

def _persist_plan(plan: Plan) -> None:
    # Store the whole plan JSON and pre-register steps + deps
    save_plan(plan.task_id, plan.model_dump_json())
    for s in plan.steps:
        upsert_step(plan.task_id, s.id)
        for d in s.depends_on:
            add_dependency(plan.task_id, s.id, d)

@app.agent(task_topic)
async def planner(stream):
    async for msg in stream:
        action = (msg.get("action") or "").strip()
        tid = msg.get("task_id") or str(uuid.uuid4())

        if not action:
            prompt = (msg.get("prompt") or "").strip()
            init_task(tid, prompt)
            _append_report({"task_id": tid, "status": "received", "summary": prompt})
            await report_topic.send(key=tid.encode(), value=make_report(tid, "received", prompt))

            # LLM planning → validate → persist
            try:
                plan = await _make_plan(tid, prompt)
            except Exception as e:
                # Fallback: static 4-step chain if planning fails
                plan = Plan(
                    task_id=tid, title=prompt, steps=[
                        {"id":"design@v1","depends_on":[]},
                        {"id":"implement@v1","depends_on":["design@v1"]},
                        {"id":"test@v1","depends_on":["implement@v1"]},
                        {"id":"review@v1","depends_on":["test@v1"]},
                    ]
                )
            _persist_plan(plan)
            _append_report({"task_id": tid, "status": "plan", "summary": f"{len(plan.steps)} steps registered"})

            # Emit all indegree-0 steps (usually just design@v1)
            ready = list_ready_steps(tid)
            for step_id in ready:
                await step_requests.send(key=tid.encode(), value={
                    "task_id": tid, "step_id": step_id, "attempt": 0, "inputs": {"prompt": prompt} if step_id=="design@v1" else {}
                })
        elif action == "replay_step":
            # Keep existing replay behavior (worker rehydrates)
            step_id = msg["step_id"]
            reason = (msg.get("reason") or "").strip()
            _append_report({"task_id": tid, "status": "replay_request", "stage": step_id, "summary": reason})
            # Ensure the step is present in steps table (in case of ad-hoc replay)
            upsert_step(tid, step_id)
            await step_requests.send(key=tid.encode(), value={
                "task_id": tid, "step_id": step_id, "attempt": 0, "inputs": {}
            })
        else:
            _append_report({"task_id": tid, "status": "error", "summary": f"unknown action: {action}"})

if __name__ == "__main__":
    app.main()
