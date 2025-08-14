import json, os, time
from pathlib import Path
from typing import Any, Dict
from app.config import load_config

def _data_dir() -> Path:
    d = load_config().get("APP_DATA_DIR", "./data")
    d.mkdir(parents=True, exist_ok=True)
    return d

def _state_path() -> Path:
    return _data_dir() / "state.json"

def _atomic_write(path: Path, data: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def load_state() -> Dict[str, Any]:
    p = _state_path()
    if not p.exists():
        return {"tasks": {}}
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"tasks": {}}

def save_state(state: Dict[str, Any]) -> None:
    _atomic_write(_state_path(), state)

def upsert_task(task_id: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    state = load_state()
    tasks = state.setdefault("tasks", {})
    task = tasks.get(task_id) or {
        "task_id": task_id,
        "spec": spec,
        "status": "pending",
        "created_at": time.time(),
        "steps": {},
        "artifacts": []
    }
    tasks[task_id] = task
    save_state(state)
    return task

def upsert_step(task_id: str, step_id: str, **fields) -> Dict[str, Any]:
    state = load_state()
    task = state.setdefault("tasks", {}).setdefault(task_id, {
        "task_id": task_id, "spec": {}, "status": "unknown", "created_at": time.time(), "steps": {}, "artifacts": []
    })
    step = task["steps"].get(step_id) or {
        "step_id": step_id, "status": "pending", "attempt": 0, "lease_id": None,
        "started_at": None, "finished_at": None, "error": None, "metrics": {}
    }
    step.update(fields)
    task["steps"][step_id] = step
    statuses = {s.get("status","pending") for s in task["steps"].values()}
    if "fail" in statuses:
        task["status"] = "fail"
    elif all(s == "ok" for s in statuses) and statuses:
        task["status"] = "done"
    else:
        task["status"] = "running"
    save_state(state)
    return step

def append_artifact(task_id: str, step_id: str, name: str, uri: str, meta: Dict[str, Any] | None = None) -> None:
    state = load_state()
    task = state.setdefault("tasks", {}).setdefault(task_id, {
        "task_id": task_id, "spec": {}, "status": "unknown", "created_at": time.time(), "steps": {}, "artifacts": []
    })
    task.setdefault("artifacts", []).append({
        "task_id": task_id,
        "step_id": step_id,
        "name": name,
        "uri": uri,
        "meta": meta or {},
        "ts": time.time()
    })
    save_state(state)
