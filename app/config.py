from __future__ import annotations
from pathlib import Path
import json, os, typing as t

def _repo_root() -> Path:
    # Works for: `python -m app.worker`, scripts, and most envs.
    if "__file__" in globals():
        return Path(__file__).resolve().parents[1]
    # Interactive / exotic launchers: walk up from cwd
    cwd = Path().resolve()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return cwd

def load_config() -> dict[str, t.Any]:
    root = _repo_root()
    cfg: dict[str, t.Any] = {
        "OPENAI_MODEL": "gpt-4o-mini",
        "REDPANDA_BROKERS": "localhost:9092",
        "TASK_TOPIC": "agent_tasks",
        "REPORT_TOPIC": "agent_reports",
        "DATA_DIR": "data",  # default relative to repo root
    }

    # 1) JSON overrides (your config_local.json)
    json_path = root / "config.local.json"
    if json_path.exists():
        cfg.update(json.loads(json_path.read_text()))

    # 2) Env overrides
    for k in list(cfg.keys()):
        v = os.getenv(k)
        if v is not None:
            cfg[k] = v

    # 3) Normalize DATA_DIR to absolute
    data_dir = Path(cfg["DATA_DIR"])
    if not data_dir.is_absolute():
        data_dir = (root / data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    cfg["DATA_DIR"] = str(data_dir)
    cfg["REPORTS_PATH"] = str(data_dir / "reports.jsonl")
    return cfg