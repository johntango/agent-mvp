# app/pipeline/promote.py  (only the story publish parts shown; keep your existing copy/mirror functions)
from __future__ import annotations
import json
from pathlib import Path
from typing import List, Dict
from app.config import load_config

def _publish_story_to_repo(story_file: str) -> List[Path]:
    """
    Copy meta/stories/<story_file> into repo generated/meta/stories/<story_file>.
    """
    cfg = load_config()
    stories_root = Path(cfg["LOCAL_STORY_ROOT"])
    src = stories_root / Path(story_file).name  # enforce basename
    if not src.exists():
        raise FileNotFoundError(f"Story file not found: {src}")

    repo_root = Path(cfg["LOCAL_REPO_PATH"])
    dst_dir = repo_root / cfg["REPO_META_STORIES_DIR"]
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    dst.write_bytes(src.read_bytes())
    return [dst]

def _read_story_ref_for_task(task_root: Path) -> str | None:
    refp = task_root / "meta" / "story_ref.json"
    if not refp.exists():
        return None
    ref = json.loads(refp.read_text(encoding="utf-8"))
    return ref.get("story_file")

def promote_to_repo(task_id: str, publish_story: bool = True) -> List[Path]:
    cfg = load_config()
    staging = Path(cfg["LOCAL_GENERATED_ROOT"]) / task_id
    repo_root = Path(cfg["LOCAL_REPO_PATH"])
    repo_task = repo_root / cfg["REPO_GENERATED_DIR"] / task_id

    written: List[Path] = []
    for sub in ("src", "tests", "meta"):
        # your existing _copy_tree(src, dst) here
        from .promote_helpers import copy_tree as _copy_tree  # if you have it refactored
        written += _copy_tree(staging / sub, repo_task / sub)

    if publish_story:
        sf = _read_story_ref_for_task(staging)
        if sf:
            written += _publish_story_to_repo(sf)
    return written
