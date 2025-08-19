# app/ci/closed_loop.py
from __future__ import annotations

import io
import json
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests
from openai import OpenAI

from app.config import load_config
from app.git_integration import prepare_repo_and_pr

# ---------- GitHub API helpers ----------

_GH = "https://api.github.com"

def _gh(method: str, path: str, token: str, *, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    r = requests.request(
        method,
        f"{_GH}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        params=params,
        timeout=60,
    )
    r.raise_for_status()
    return r.json() if (r.text or "").strip() else {}

def _download(url: str, token: str) -> bytes:
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=120)
    r.raise_for_status()
    return r.content

# ---------- JUnit parsing ----------

def _parse_junit_bytes(xml_bytes: bytes) -> Dict[str, Any]:
    """Return totals + list of failures/errors with messages and trace text."""
    import xml.etree.ElementTree as ET
    out: Dict[str, Any] = {"total": 0, "failures": 0, "errors": 0, "tests": []}
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return out

    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    for suite in suites:
        out["total"] += int(suite.attrib.get("tests", "0") or 0)
        out["failures"] += int(suite.attrib.get("failures", "0") or 0)
        out["errors"] += int(suite.attrib.get("errors", "0") or 0)
        for case in suite.iter("testcase"):
            name = case.attrib.get("name", "")
            cls = case.attrib.get("classname", "")
            nodeid = f"{cls}::{name}" if cls else name
            for kind in ("failure", "error"):
                el = case.find(kind)
                if el is not None:
                    out["tests"].append({
                        "nodeid": nodeid,
                        "type": kind.upper(),
                        "message": (el.attrib.get("message") or "").strip(),
                        "text": (el.text or "").strip(),
                    })
    return out

# ---------- CI polling + artifact download ----------

@dataclass
class CIRunResult:
    conclusion: str                 # success | failure | cancelled | neutral | timed_out
    run_id: int | None
    per_task: Dict[str, Dict[str, Any]]

def _wait_for_ci(owner_repo: str, head_sha: str, token: str,
                 *, timeout_s: int = 900, poll_s: int = 10) -> Tuple[str, int | None]:
    """
    Poll workflow runs by head_sha until one completes or timeout.
    Returns (conclusion, run_id or None).
    """
    owner, repo = owner_repo.split("/", 1)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        data = _gh("GET", f"/repos/{owner}/{repo}/actions/runs",
                   token, params={"head_sha": head_sha, "per_page": 5})
        runs = data.get("workflow_runs") or []
        if runs:
            run = runs[0]
            status = run.get("status")
            conclusion = run.get("conclusion") or "neutral"
            if status == "completed":
                return conclusion, int(run["id"])
        time.sleep(poll_s)
    return "timed_out", None

def _collect_junit(owner_repo: str, run_id: int, token: str) -> Dict[str, Dict[str, Any]]:
    """
    Download artifacts for a run and extract junit summaries.
    Expects artifacts named 'junit-<taskId>'.
    Returns { "<taskId>": junit_dict }.
    """
    owner, repo = owner_repo.split("/", 1)
    arts = _gh("GET", f"/repos/{owner}/{repo}/actions/runs/{run_id}/artifacts", token)
    per_task: Dict[str, Dict[str, Any]] = {}
    for a in arts.get("artifacts", []):
        name = a.get("name", "")
        if not name.startswith("junit-") or a.get("expired"):
            continue
        task_id = name[len("junit-"):]
        zip_bytes = _download(a["archive_download_url"], token)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            # take the first *.xml
            xml_name = next((n for n in zf.namelist() if n.endswith(".xml")), None)
            if xml_name:
                junit = _parse_junit_bytes(zf.read(xml_name))
                per_task[task_id] = junit
    return per_task

# ---------- Implementation improvement ----------

def _choose_target_src_file(src_dir: Path) -> Path | None:
    py = sorted(src_dir.rglob("*.py"))
    if not py:
        return None
    # Prefer shipping_* or main.py if present
    for prefer in ("shipping", "main"):
        for p in py:
            if prefer in p.name:
                return p
    return py[0]

def _improve_impl_with_failures(task_id: str, design: Dict[str, Any], impl: Dict[str, Any],
                                junit_summary: Dict[str, Any]) -> List[Path]:
    """
    Calls the LLM to patch the implementation given failing nodeids/messages.
    Writes to LOCAL_GENERATED_ROOT/<taskId>/src, returns list of written paths.
    """
    cfg = load_config()
    src_dir = Path(cfg["LOCAL_GENERATED_ROOT"]) / task_id / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    target = _choose_target_src_file(src_dir) or (src_dir / "shipping_cost.py")
    current = target.read_text(encoding="utf-8") if target.exists() else ""

    prompt = f"""You are a precise Python fixer.

Design summary:
{json.dumps(design, indent=2)}

Implementation summary:
{json.dumps({k: impl.get(k) for k in ('diff_summary','code_snippets','files') if k in impl}, indent=2)}

Current file: {target.name}
---
{current}
---

Failing tests summary (first 2 as provided by CI):
{json.dumps(junit_summary, indent=2)}

Goal:
- Produce a corrected, complete replacement for {target.name} only.
- Keep the public API stable.
- Emit ONLY the code for {target.name}; no prose, no fences.
"""

    client = OpenAI()
    model = (impl.get("model") or
             cfg.get("IMPROVE_MODEL") or
             "gpt-4o-mini")
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You output only valid Python source for the specified file."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    code = (resp.choices[0].message.content or "").strip()
    if not code:
        return []
    target.write_text(code, encoding="utf-8")
    return [target]

# ---------- Public API: one-call closed loop ----------

def run_ci_closed_loop(task_id: str, pr_info: Dict[str, Any],
                       design: Dict[str, Any], impl: Dict[str, Any],
                       *, max_rounds: int = 1, poll_s: int = 10, timeout_s: int = 900) -> Dict[str, Any]:
    """
    Synchronous closed loop:
      PR → wait for CI → on failure: fetch junit, patch impl, push new commit → (repeat)
    Returns final {"conclusion": "...", "rounds": N}.
    """
    cfg = load_config()
    token = cfg["GITHUB_TOKEN"]
    owner_repo = pr_info["repo"]
    head_sha = pr_info["head_sha"]

    result: Dict[str, Any] = {"conclusion": "unknown", "rounds": 0}

    for round_idx in range(1, max_rounds + 1):
        conclusion, run_id = _wait_for_ci(owner_repo, head_sha, token, timeout_s=timeout_s, poll_s=poll_s)
        result["rounds"] = round_idx
        result["conclusion"] = conclusion

        # Save quick CI status
        meta = Path(cfg["LOCAL_GENERATED_ROOT"]) / task_id / "meta"
        meta.mkdir(parents=True, exist_ok=True)
        (meta / f"ci_round_{round_idx}_status.json").write_text(
            json.dumps({"conclusion": conclusion, "run_id": run_id}, indent=2), encoding="utf-8"
        )

        if conclusion in ("success", "skipped"):
            return result
        if run_id is None:
            # timed out or no run found
            return result

        # Collect junit; require this task's artifact
        per_task = _collect_junit(owner_repo, run_id, token)
        junit = per_task.get(task_id)
        (meta / f"ci_round_{round_idx}_junit.json").write_text(
            json.dumps({"per_task_keys": list(per_task.keys()), "this_task": junit}, indent=2),
            encoding="utf-8"
        )
        if not junit or (junit.get("failures", 0) + junit.get("errors", 0) == 0):
            # No actionable failures (could be infrastructure issue). Stop.
            return result

        # Improve implementation and push a new commit on the same branch
        written = _improve_impl_with_failures(task_id, design, impl, junit)
        if not written:
            return result

        # Reuse prepare_repo_and_pr to stage + push (same branch "task/<taskId>")
        pr2 = prepare_repo_and_pr(task_id, design, impl, tests={})
        # Update head_sha for next polling round (if commit changed)
        head_sha = pr2.get("head_sha") or head_sha

    return result
