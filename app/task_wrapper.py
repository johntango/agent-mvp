# app/task_wrapper.py
from __future__ import annotations
import json, importlib, textwrap, shutil
from pathlib import Path
from typing import Any, Dict, List

from app.config import load_config
from app.git_integration import prepare_repo_and_pr

_TEMPLATE = """\
import pytest
from decimal import Decimal
from {module} import {function}{extra_imports}

{body}
"""

_CASE_OK = """\
def test_{name}():
    out = {function}({args})
    assert str(out) == "{expected}"
"""

_CASE_ERR = """\
def test_{name}():
    with pytest.raises({exc}):
        {function}({args})
"""

def _fmt_args(d: Dict[str, Any]) -> str:
    def q(v):
        if isinstance(v, str):
            return f'"{v}"'
        return repr(v)
    return ", ".join(f"{k}={q(v)}" for k, v in d.items())

def _generate_tests_from_story_json(story_spec: Dict[str, Any], out_dir: Path) -> Path:
    module = story_spec["module"]
    function = story_spec["function"]
    cases: List[Dict[str, Any]] = story_spec.get("cases", [])

    extra_imports = ""
    try:
        mod = importlib.import_module(module)
        excs = {c["expect"]["raises"]
                for c in cases
                if isinstance(c.get("expect"), dict) and "raises" in c["expect"]}
        present = [e for e in excs if hasattr(mod, e)]
        if present:
            extra_imports = ", " + ", ".join(sorted(set(present)))
    except Exception:
        pass

    body_parts: List[str] = []
    for c in cases:
        name = c["name"]
        args = _fmt_args(c["inputs"])
        exp = c.get("expect", {})
        if "equals" in exp:
            body_parts.append(_CASE_OK.format(name=name, function=function, args=args, expected=exp["equals"]))
        elif "raises" in exp:
            body_parts.append(_CASE_ERR.format(name=name, function=function, args=args, exc=exp["raises"]))
        else:
            raise ValueError(f"Case '{name}' missing 'expect.equals' or 'expect.raises'")

    content = _TEMPLATE.format(
        module=module,
        function=function,
        extra_imports=extra_imports,
        body="\n\n".join(body_parts),
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"test_{function}.py"
    out_path.write_text(textwrap.dedent(content), encoding="utf-8")
    return out_path

def generate_and_publish_task(task_id: str, story_id: str, design_summary: str = "") -> Dict[str, Any]:
    """
    1) Read central story: LOCAL_STORY_ROOT/<story_id>.json
    2) Generate pytest tests under LOCAL_GENERATED_ROOT/<taskId>/tests/
    3) Snapshot story.json into LOCAL_GENERATED_ROOT/<taskId>/meta/story.json
    4) Call prepare_repo_and_pr(...) (copies code+tests+meta into repo; commit; push; PR)
    """
    cfg = load_config()

    # Central story (not under task)
    story_path = Path(cfg["LOCAL_STORY_ROOT"]) / f"{story_id}.json"
    if not story_path.exists():
        raise FileNotFoundError(f"Story not found: {story_path}")

    story_spec = json.loads(story_path.read_text(encoding="utf-8"))

    # Task-local dirs (these are what git_integration will copy from)
    local_task_dir = Path(cfg["LOCAL_GENERATED_ROOT"]) / task_id
    tests_dir = local_task_dir / "tests"
    meta_dir = local_task_dir / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)

    # Generate tests from central story into the task-local tests folder
    test_file = _generate_tests_from_story_json(story_spec, tests_dir)
    print(f"[wrapper] generated tests → {test_file}")

    # Snapshot the story under the task (for PR auditability)
    snapshot_rel = Path(cfg["REPO_STORY_SNAPSHOT_REL"])  # typically "meta/story.json"
    snapshot_local_path = local_task_dir / snapshot_rel
    snapshot_local_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_local_path.write_text(json.dumps(story_spec, indent=2), encoding="utf-8")
    print(f"[wrapper] snapshotted story → {snapshot_local_path}")

    # Optionally check for src/ existence
    src_dir = local_task_dir / "src"
    if not src_dir.exists():
        print(f"[wrapper] NOTE: no src/ at {src_dir}; PR may contain only tests/meta unless src is added")

    design = {"design_summary": design_summary}
    impl: Dict[str, Any] = {}    # rely on LOCAL fallback in git_integration
    tests: Dict[str, Any] = {}   # rely on LOCAL fallback in git_integration

    return prepare_repo_and_pr(task_id, design, impl, tests)

# Optional CLI
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python -m app.task_wrapper <task_id> <story_id> [design_summary]")
        raise SystemExit(2)
    task_id = sys.argv[1]
    story_id = sys.argv[2]
    summary = sys.argv[3] if len(sys.argv) > 3 else ""
    info = generate_and_publish_task(task_id, story_id, summary)
    print(json.dumps(info, indent=2))
