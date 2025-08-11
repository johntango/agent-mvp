# app/worker.py
import os, json
from pathlib import Path
from typing import Any, Tuple

from agents import Runner
from app.bus import app, task_topic, report_topic, make_report
from app.agents import (
    make_architect_agent, make_implementer_agent,
    make_tester_agent, make_reviewer_agent
)
from app.config import load_config

cfg = load_config()
DATA_DIR = Path(cfg["DATA_DIR"])
DATA_DIR.mkdir(parents=True, exist_ok=True)

def _to_jsonable(obj: Any) -> Any:
    """Coerce Pydantic models and other objects to JSON-serializable values."""
    try:
        from pydantic import BaseModel  # type: ignore
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

@app.agent(task_topic)
async def handle_tasks(stream):
    async for task in stream:  # dict due to value_serializer='json'
        tid = task.get("task_id", "unknown")
        task_dir = DATA_DIR / tid
        try:
            prompt = task["prompt"]

            # Run each agent explicitly so we can capture results to files
            arch = make_architect_agent()
            arch_res = await Runner.run(arch, prompt)
            _write_json(task_dir / "architect.json", arch_res.final_output)

            impl = make_implementer_agent()
            impl_res = await Runner.run(impl, prompt, context={"design": _to_jsonable(arch_res.final_output)})
            _write_json(task_dir / "implementer.json", impl_res.final_output)

            tester = make_tester_agent()
            test_res = await Runner.run(tester, prompt, context={"design": _to_jsonable(arch_res.final_output),
                                                                 "impl": _to_jsonable(impl_res.final_output)})
            _write_json(task_dir / "tester.json", test_res.final_output)

            reviewer = make_reviewer_agent()
            rev_res = await Runner.run(reviewer, prompt, context={"design": _to_jsonable(arch_res.final_output),
                                                                  "impl": _to_jsonable(impl_res.final_output),
                                                                  "tests": _to_jsonable(test_res.final_output)})
            _write_json(task_dir / "reviewer.json", rev_res.final_output)

            # Build a human-readable summary for the report/log
            summary = f"Task {tid}: artifacts written to {task_dir}"
            await report_topic.send(
                key=tid.encode(),
                value=make_report(tid, "done", summary)
            )

            # Also append to the JSONL the UI shows
            with (DATA_DIR / "reports.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"task_id": tid, "status": "done", "summary": summary}) + "\n")

        except Exception as e:
            err = f"error: {e}"
            await report_topic.send(key=str(tid).encode(), value=make_report(tid, "error", err))
            with (DATA_DIR / "reports.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"task_id": tid, "status": "error", "summary": err}) + "\n")
if __name__ == "__main__":
    app.main()
