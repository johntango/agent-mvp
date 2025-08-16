# app/gitflow/staging.py
from pathlib import Path
from typing import Dict, List

from app.config import load_config


def prepare_files_from_local(task_id: str) -> Dict[str, List[Path]]:
    """
    Collects files from LOCAL_GENERATED_ROOT/<taskId>/{src,tests,meta} if present.
    No requirement that meta/story.json exists. Any meta/* (e.g., story_ref.json) is included.
    """
    cfg = load_config()
    base = Path(cfg["LOCAL_GENERATED_ROOT"]) / task_id

    buckets = {}
    for name in ("src", "tests", "meta"):
        p = base / name
        if p.exists():
            buckets[name] = [f for f in p.rglob("*") if f.is_file()]
        else:
            buckets[name] = []
    return buckets