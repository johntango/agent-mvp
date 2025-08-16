import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import load_config
from openai import OpenAI  # or your LLM wrapper


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _canonical_json_bytes(obj) -> bytes:
    # Deterministic hashing for provenance
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _write_story_ref(meta_dir: Path, story_id: str, story_obj: dict) -> Path:
    meta_dir.mkdir(parents=True, exist_ok=True)
    ref = {
        "story_id": story_id,
        "story_sha256": _sha256_bytes(_canonical_json_bytes(story_obj)),
        "written_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "note": "Pointer only; full story is stored under LOCAL_STORY_ROOT/<story_id>/story.json",
    }
    ref_path = meta_dir / "story_ref.json"
    ref_path.write_text(json.dumps(ref, indent=2), encoding="utf-8")
    return ref_path


def generate_tests_from_story(task_id: str, story_id: str) -> Path:
    """
    Reads story.json from /stories/<story_id>/story.json (global registry) and
    generates test files into /generated/<taskId>/tests. Does NOT copy story.json
    into the task directory. Writes a pointer 'story_ref.json' for provenance.
    """
    cfg = load_config()
    stories_root = Path(cfg["LOCAL_STORY_ROOT"])
    story_path = stories_root / story_id / "story.json"

    if not story_path.exists():
        raise FileNotFoundError(f"No story.json found at {story_path}")

    story_raw = story_path.read_text(encoding="utf-8")
    story = json.loads(story_raw)

    # Required/optional fields (robust to partial stories)
    feature = story.get("feature", "unknown feature")
    requirements = story.get("requirements", "")
    acceptance = story.get("acceptance", "")
    constraints = story.get("constraints", "")

    # Task-local output locations
    gen_root = Path(cfg["LOCAL_GENERATED_ROOT"]) / task_id
    tests_dir = gen_root / "tests"
    meta_dir = gen_root / "meta"
    tests_dir.mkdir(parents=True, exist_ok=True)

    # Write provenance pointer (no full story copy)
    _write_story_ref(meta_dir, story_id, story)

    # Prompting
    prompt = f"""
You are a test generator. Based on this product story:

Feature: {feature}

Functional Requirements:
{requirements}

Acceptance Criteria:
{acceptance}

Non-functional Constraints (if any):
{constraints}

Produce **pytest** tests in Python that validate the described behavior.
- Use deterministic, self-contained tests (no network calls).
- Include clear test names and docstrings.
- If requirements imply multiple behaviors, split into multiple test functions.
- If interfaces are not specified, define minimal stubs/mocks to make tests runnable.
Return only the code for one or more files. Do not include prose.
"""

    client = OpenAI()  # assumes API key in env
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )

    content = response.choices[0].message["content"].strip()

    # Minimal parsing: single file fallback
    test_file = tests_dir / "test_story.py"
    test_file.write_text(content, encoding="utf-8")
    return test_file


def main():
    parser = argparse.ArgumentParser(description="Generate tests from a shared story.")
    parser.add_argument("--task", dest="task_id", required=True, help="task identifier")
    parser.add_argument("--story", dest="story_id", required=True, help="story identifier under LOCAL_STORY_ROOT")
    args = parser.parse_args()
    test_path = generate_tests_from_story(args.task_id, args.story_id)
    print(f"[test-generator] wrote {test_path}")


if __name__ == "__main__":
    main()