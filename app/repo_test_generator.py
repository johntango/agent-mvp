# app/agents/repo_test_generator.py
from __future__ import annotations
import json, textwrap, importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from app.config import load_config


@dataclass(frozen=True)
class StoryCase:
    name: str
    inputs: Dict[str, Any]
    expect: Dict[str, Any]  # {"equals": str} | {"raises": "ValueError"} | {"approx": {"value": 1.23, "abs": 1e-6}}

@dataclass(frozen=True)
class StorySpec:
    feature: str
    module: str
    function: str
    cases: List[StoryCase]


def _repo_task_root(task_id: str) -> Path:
    cfg = load_config()
    return Path(cfg["GIT_LOCAL_REPO_PATH"]) / cfg["REPO_GENERATED_DIR"] / task_id

def _load_repo_story(task_id: str) -> Dict[str, Any]:
    story_path = _repo_task_root(task_id) / "meta" / "story.json"
    if not story_path.exists():
        raise FileNotFoundError(f"story.json not found at {story_path}")
    return json.loads(story_path.read_text(encoding="utf-8"))

def _coerce_story(spec: Dict[str, Any]) -> StorySpec:
    try:
        feature = str(spec.get("feature", spec.get("title", "Unnamed Feature")))
        module = str(spec["module"])
        function = str(spec["function"])
        raw_cases = spec.get("cases", [])
        cases: List[StoryCase] = []
        for c in raw_cases:
            cases.append(StoryCase(
                name=str(c["name"]),
                inputs=dict(c.get("inputs", {})),
                expect=dict(c["expect"]),
            ))
        if not cases:
            raise ValueError("story.cases is empty")
        return StorySpec(feature=feature, module=module, function=function, cases=cases)
    except Exception as e:
        raise ValueError(f"Invalid story spec: {e}") from e

def _fmt_arg(v: Any) -> str:
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    return repr(v)

def _fmt_kwargs(d: Dict[str, Any]) -> str:
    return ", ".join(f"{k}={_fmt_arg(v)}" for k, v in d.items())

def _render_pytest_module(story: StorySpec) -> str:
    # try to import the module to optionally import custom exceptions
    extra_imports = ""
    try:
        mod = importlib.import_module(story.module)
        excs = {c.expect.get("raises") for c in story.cases if "raises" in c.expect}
        present = [e for e in excs if isinstance(e, str) and hasattr(mod, e)]
        if present:
            extra_imports = ", " + ", ".join(sorted(set(present)))
    except Exception:
        pass

    header = textwrap.dedent(f"""\
        import pytest
        from {story.module} import {story.function}{extra_imports}
    """)

    equals_cases = [c for c in story.cases if "equals" in c.expect]
    approx_cases  = [c for c in story.cases if "approx" in c.expect]
    raises_cases  = [c for c in story.cases if "raises" in c.expect]

    parts: List[str] = []

    if equals_cases:
        rows = [
            f'("{c.name}", dict({_fmt_kwargs(c.inputs)}), {json.dumps(str(c.expect["equals"]))})'
            for c in equals_cases
        ]
        parts.append(textwrap.dedent(f"""\
            @pytest.mark.parametrize("name,kwargs,expected_str", [
                {",\n                ".join(rows)}
            ])
            def test_{story.function}_equals(name, kwargs, expected_str):
                out = {story.function}(**kwargs)
                assert str(out) == expected_str
        """))

    if approx_cases:
        rows = []
        for c in approx_cases:
            ap = c.expect["approx"]
            args = [repr(ap.get("value"))]
            if "abs" in ap: args.append(f"abs={ap['abs']}")
            if "rel" in ap: args.append(f"rel={ap['rel']}")
            rows.append(f'("{c.name}", dict({_fmt_kwargs(c.inputs)}), pytest.approx({", ".join(args)}))')
        parts.append(textwrap.dedent(f"""\
            @pytest.mark.parametrize("name,kwargs,target", [
                {",\n                ".join(rows)}
            ])
            def test_{story.function}_approx(name, kwargs, target):
                out = {story.function}(**kwargs)
                assert out == target
        """))

    if raises_cases:
        rows = [
            f'("{c.name}", dict({_fmt_kwargs(c.inputs)}), {c.expect["raises"]})'
            for c in raises_cases
        ]
        parts.append(textwrap.dedent(f"""\
            @pytest.mark.parametrize("name,kwargs,exc", [
                {",\n                ".join(rows)}
            ])
            def test_{story.function}_raises(name, kwargs, exc):
                with pytest.raises(exc):
                    {story.function}(**kwargs)
        """))

    if not parts:
        parts.append(textwrap.dedent(f"""\
            def test_{story.function}_smoke():
                assert callable({story.function})
        """))

    return header + "\n\n".join(parts) + "\n"

def _ensure_conftest(tests_dir: Path) -> Path:
    conftest = tests_dir / "conftest.py"
    if not conftest.exists():
        content = """\
import sys, pathlib
# tests/ is at generated/<taskId>/tests -> parent is generated/<taskId>
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
"""
        tests_dir.mkdir(parents=True, exist_ok=True)
        conftest.write_text(textwrap.dedent(content), encoding="utf-8")
    return conftest

def generate_repo_tests_from_story(task_id: str) -> list[Path]:
    """
    Read meta/story.json from:
      <GIT_LOCAL_REPO_PATH>/<REPO_GENERATED_DIR>/<taskId>/meta/story.json
    and write pytest tests into:
      <GIT_LOCAL_REPO_PATH>/<REPO_GENERATED_DIR>/<taskId>/tests/
    """
    root = _repo_task_root(task_id)
    story_spec = _load_repo_story(task_id)
    story = _coerce_story(story_spec)

    tests_dir = root / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    _ensure_conftest(tests_dir)

    test_code = _render_pytest_module(story)
    test_path = tests_dir / f"test_{story.function}.py"
    test_path.write_text(test_code, encoding="utf-8")

    print(f"[repo_test_gen] wrote tests → {test_path}")
    return [test_path]
