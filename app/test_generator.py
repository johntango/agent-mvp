from __future__ import annotations
import argparse, hashlib, json, os
from datetime import datetime, timezone
from pathlib import Path
from openai import OpenAI
from app.config import load_config

def _sha256_bytes(b: bytes) -> str:
    import hashlib
    return hashlib.sha256(b).hexdigest()

def _canonical_json_bytes(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")

def _write_story_ref(meta_dir: Path, story_id: str, story_obj: dict) -> Path:
    meta_dir.mkdir(parents=True, exist_ok=True)
    ref = {
        "story_id": story_id,
        "story_sha256": _sha256_bytes(_canonical_json_bytes(story_obj)),
        "written_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "note": "Pointer only; full story lives in LOCAL_STORY_ROOT and is published to repo under generated/meta/stories.",
    }
    p = meta_dir / "story_ref.json"
    p.write_text(json.dumps(ref, indent=2), encoding="utf-8")
    return p

def generate_tests_from_story(task_id: str, story_id: str, model: str = os.getenv("TEST_GEN_MODEL","gpt-4o-mini")) -> list[Path]:
    cfg = load_config()
    story_path = Path(cfg["LOCAL_STORY_ROOT"]) / story_id / "story.json"
    if not story_path.exists():
        raise FileNotFoundError(f"No story.json at {story_path}")

    story = json.loads(story_path.read_text(encoding="utf-8"))
    feature = story.get("feature", "unknown feature")
    requirements = story.get("requirements", "")
    acceptance = story.get("acceptance", "")
    constraints = story.get("constraints", "")

    gen_root = Path(cfg["LOCAL_GENERATED_ROOT"]) / task_id
    tests_dir = gen_root / "tests"
    meta_dir = gen_root / "meta"
    tests_dir.mkdir(parents=True, exist_ok=True)

    _write_story_ref(meta_dir, story_id, story)

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
        messages=[{"role":"system","content":"Generate clean, deterministic pytest tests."},
                  {"role":"user","content":prompt}],
        temperature=0.2,
    )
    code = (resp.choices[0].message.content or "").strip()
    out = tests_dir / "test_story.py"
    out.write_text(code, encoding="utf-8")
    return [out]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--story", required=True)
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    generate_tests_from_story(a.task, a.story, model=a.model or "gpt-4o-mini")