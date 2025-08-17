# app/agents/test_generator.py
from __future__ import annotations
import argparse
import json
import os
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

from openai import OpenAI
from app.config import load_config


def _stories_dir(cfg: Dict[str, Any]) -> Path:
    return Path(cfg["LOCAL_STORY_ROOT"])  # "/workspaces/agent-mvp/meta/stories"
def _strip_code_fences(s: str) -> str:
    s = s.strip()
    # ```python\n...\n```  or ```\n...\n```
    m = re.match(r"^```(?:[Pp]ython)?\s*(.*?)\s*```$", s, re.S)
    return m.group(1) if m else s

# …after the chat completion:
code = (resp.choices[0].message.content or "").strip()
code = _strip_code_fences(code)
if not code.strip():
    raise RuntimeError("LLM returned empty test content")
(test_dir / "test_story.py").write_text(code, encoding="utf-8")

def _discover_single_story(stories_root: Path) -> Path:
    """If exactly one *.json exists in meta/stories, return it; else raise."""
    candidates = sorted([p for p in stories_root.glob("*.json") if p.is_file()])
    if len(candidates) == 1:
        return candidates[0]
    raise FileNotFoundError(
        f"Ambiguous story selection in {stories_root}. "
        f"Found {[p.name for p in candidates]}. Pass --story-file explicitly."
    )


def _resolve_story_file(cfg: Dict[str, Any], story_file: Optional[str]) -> Path:
    root = _stories_dir(cfg)
    if story_file:
        p = Path(story_file)
        if not p.is_absolute():
            p = root / p.name
        if not p.exists():
            raise FileNotFoundError(f"Story file not found: {p}")
        return p
    return _discover_single_story(root)


def _write_story_ref(meta_dir: Path, story_path: Path, story_obj: dict) -> Path:
    meta_dir.mkdir(parents=True, exist_ok=True)
    ref = {
        "story_file": story_path.name,
        "story_sha256": sha256(json.dumps(story_obj, sort_keys=True, separators=(',', ':')).encode("utf-8")).hexdigest(),
        "written_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "note": "Pointer only; full story lives under meta/stories/<filename>.json and is published to repo generated/meta/stories/",
    }
    out = meta_dir / "story_ref.json"
    out.write_text(json.dumps(ref, indent=2), encoding="utf-8")
    return out


def generate_tests_from_story(task_id: str, story_file: Optional[str] = None, model: Optional[str] = None) -> List[Path]:
    """
    Reads a STORY JSON file directly from meta/stories/*.json (no storyId).
    Writes pytest tests under generated/<taskId>/tests and a meta/story_ref.json.
    """
    cfg = load_config()
    model = model or os.getenv("TEST_GEN_MODEL", "gpt-4o-mini")

    story_path = _resolve_story_file(cfg, story_file)
    story = json.loads(story_path.read_text(encoding="utf-8"))

    feature = story.get("feature", "unknown feature")
    requirements = story.get("requirements", "")
    acceptance = story.get("acceptance", "")
    constraints = story.get("constraints", "")

    gen_root = Path(cfg["LOCAL_GENERATED_ROOT"]) / task_id
    tests_dir = gen_root / "tests"
    meta_dir = gen_root / "meta"
    tests_dir.mkdir(parents=True, exist_ok=True)

    _write_story_ref(meta_dir, story_path, story)

    prompt = f"""You are a precise pytest generator.

Feature: {feature}

Functional Requirements:
{requirements}

Acceptance Criteria:
{acceptance}

Non-functional Constraints:
{constraints}

Emit runnable pytest tests only (Python 3.11), no prose."""

    client = OpenAI()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Generate clean, deterministic pytest tests."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    code = (resp.choices[0].message.content or "").strip()
    out = tests_dir / "test_story.py"
    out.write_text(code, encoding="utf-8")
    return [out]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate pytest files from a story file under meta/stories.")
    ap.add_argument("--task", required=True, help="task identifier")
    ap.add_argument("--story-file", default=None, help="filename under meta/stories (e.g., login.json). If omitted and exactly one story exists, that one is used.")
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    generate_tests_from_story(a.task, a.story_file, a.model)
