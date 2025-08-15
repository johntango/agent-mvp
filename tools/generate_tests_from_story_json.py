import sys, json, importlib, textwrap
from pathlib import Path
from typing import Dict, Any

TEMPLATE = """\
import pytest
from decimal import Decimal
from {module} import {function}{extra_imports}

{body}
"""

CASE_OK = """\
def test_{name}():
    out = {function}({args})
    assert str(out) == "{expected}"
"""

CASE_ERR = """\
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

def main(story_json: str, out_dir: str):
    spec = json.loads(Path(story_json).read_text(encoding="utf-8"))
    module = spec["module"]
    function = spec["function"]
    cases = spec.get("cases", [])

    # Try to import the module to gather exception classes for proper import lines.
    extra_imports = ""
    try:
        mod = importlib.import_module(module)
        excs = {c["expect"]["raises"]
                for c in cases
                if isinstance(c.get("expect"), dict) and "raises" in c["expect"]}
        # keep only names that exist on the module; fall back to plain names otherwise
        present = [e for e in excs if hasattr(mod, e)]
        if present:
            extra_imports = ", " + ", ".join(sorted(set(present)))
    except Exception:
        pass  # Module may not exist yet; tests can still be generated.

    body_parts = []
    for c in cases:
        name = c["name"]
        args = _fmt_args(c["inputs"])
        exp = c.get("expect", {})
        if "equals" in exp:
            body_parts.append(CASE_OK.format(name=name, function=function, args=args, expected=exp["equals"]))
        elif "raises" in exp:
            body_parts.append(CASE_ERR.format(name=name, function=function, args=args, exc=exp["raises"]))
        else:
            raise ValueError(f"Case '{name}' missing a valid 'expect' clause (equals|raises).")

    content = TEMPLATE.format(module=module, function=function,
                              extra_imports=extra_imports, body="\n\n".join(body_parts))

    out_path = Path(out_dir) / f"test_{function}.py"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(textwrap.dedent(content), encoding="utf-8")
    print(f"Wrote {out_path}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python tools/generate_tests_from_story_json.py <story.json> <out_dir>")
        sys.exit(2)
    main(sys.argv[1], sys.argv[2])
