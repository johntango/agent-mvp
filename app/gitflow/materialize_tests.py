# app/pipeline/materialize_tests.py
from __future__ import annotations
import json, re
from pathlib import Path
from typing import Optional, Dict, Any, List
from app.config import load_config

# Optional: if your generator lives here
from app.test_generator import generate_tests_from_story


def _has_any_tests(tid: str, cfg: Dict[str, Any]) -> bool:
    tests_dir = Path(cfg["LOCAL_GENERATED_ROOT"]) / tid / "tests"
    return tests_dir.exists() and any(tests_dir.rglob("*.py"))

def _infer_story_file(cfg: Dict[str, Any]) -> Optional[str]:
    """Choose a single story file under meta/stories; return None if ambiguous/none."""
    root = Path(cfg["LOCAL_STORY_ROOT"])
    files = sorted([p.name for p in root.glob("*.json") if p.is_file()])
    if len(files) == 1:
        return files[0]
    return None

def ensure_tests_for_task(tid: str, *, story_file: Optional[str] = None) -> List[Path]:
    """
    Idempotent: if tests already exist under generated/<tid>/tests, no-op.
    Otherwise, calls test generator using provided story_file, or auto-infers
    the single story file in meta/stories.
    Returns list of written file paths (or []).
    """
    cfg = load_config()
    if _has_any_tests(tid, cfg):
        return []

    sf = story_file or _infer_story_file(cfg)
    if not sf:
        raise RuntimeError(
            "No tests present and story_file could not be inferred. "
            "Place exactly one *.json in meta/stories or pass an explicit story filename."
        )

    # Generate pytest locally
    return generate_tests_from_story(task_id=tid, story_file=sf)
