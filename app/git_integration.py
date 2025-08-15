# app/git_integration.py
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import fnmatch

import requests  # pip install requests
from app.config import load_config

# ---------------------------------------------------------------------------
# Allow-list: only code, tests, and minimal meta get committed
# ---------------------------------------------------------------------------
ALLOWED_GLOBS = [
    "src/**/*.py",
    "src/**/pyproject.toml",
    "tests/**/*.py",
    "meta/MANIFEST.json",
    "meta/README.md",
    "meta/REPORT.md",
    "meta/story.json",   # snapshot for auditability
    "README.md",
]

def _match_any(rel: Path) -> bool:
    s = str(rel).replace("\\", "/")
    return any(fnmatch.fnmatch(s, pat) for pat in ALLOWED_GLOBS)

# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------

def _run(cmd: str, cwd: Path, env: Optional[dict] = None) -> Tuple[int, str, str]:
    e = os.environ.copy()
    if env:
        e.update(env)
    p = subprocess.Popen(
        shlex.split(cmd),
        cwd=str(cwd),
        env=e,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    out, err = p.communicate()
    return p.returncode, (out or "").strip(), (err or "").strip()

def _ensure_ok(code: int, out: str, err: str, ctx: str) -> None:
    if code != 0:
        raise RuntimeError(f"{ctx} failed: {err or out}")

# ---------------------------------------------------------------------------
# GitHub API helper
# ---------------------------------------------------------------------------

def _gh_api(
    method: str,
    endpoint: str,
    token: str,
    data: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    url = f"https://api.github.com{endpoint}"
    r = requests.request(method, url, headers=headers, json=data, params=params, timeout=30)
    r.raise_for_status()
    return r.json() if (r.text or "").strip() else {}

# ---------------------------------------------------------------------------
# Git local clone management
# ---------------------------------------------------------------------------

def ensure_repo(target_path: Path, repo_url: Optional[str]) -> None:
    """
    Ensure target_path is a Git working tree (clone if needed).
    Clones into '.' so the repo populates target_path directly.
    """
    target_path.mkdir(parents=True, exist_ok=True)
    if not (target_path / ".git").exists():
        if repo_url:
            code, out, err = _run(f"git clone {shlex.quote(repo_url)} .", cwd=target_path)
            _ensure_ok(code, out, err, "git clone")
        else:
            code, out, err = _run("git init", cwd=target_path)
            _ensure_ok(code, out, err, "git init")

def ensure_remote(target_path: Path, repo_https_url_with_auth: str) -> None:
    """
    Ensure 'origin' exists and points to the tokenized HTTPS URL.
    """
    code, out, err = _run("git remote get-url origin", cwd=target_path)
    if code != 0:
        code, out, err = _run(f"git remote add origin {shlex.quote(repo_https_url_with_auth)}", cwd=target_path)
        _ensure_ok(code, out, err, "git remote add")
    else:
        if out.strip() != repo_https_url_with_auth:
            code, out, err = _run(f"git remote set-url origin {shlex.quote(repo_https_url_with_auth)}", cwd=target_path)
            _ensure_ok(code, out, err, "git remote set-url")

def checkout_base(target_path: Path, base_branch: str) -> None:
    """
    Fetch and create/reset a local base branch aligned with origin/base_branch if present.
    """
    code, out, err = _run("git fetch origin --prune", cwd=target_path)
    _ensure_ok(code, out, err, "git fetch")

    code, out, err = _run(f"git rev-parse --verify origin/{shlex.quote(base_branch)}", cwd=target_path)
    if code == 0:
        code, out, err = _run(
            f"git checkout -B {shlex.quote(base_branch)} origin/{shlex.quote(base_branch)}",
            cwd=target_path,
        )
        _ensure_ok(code, out, err, "git checkout base from origin")
    else:
        code, out, err = _run(f"git checkout -B {shlex.quote(base_branch)}", cwd=target_path)
        _ensure_ok(code, out, err, "git checkout local base")

def checkout_feature(target_path: Path, branch: str, base: str) -> None:
    """
    Create/reset the feature branch from origin/base (if exists) or local base; ensure HEAD is on branch.
    """
    code, out, err = _run("git fetch origin --prune", cwd=target_path)
    _ensure_ok(code, out, err, "git fetch")

    code, out, err = _run(f"git rev-parse --verify origin/{shlex.quote(base)}", cwd=target_path)
    if code == 0:
        code, out, err = _run(
            f"git checkout -B {shlex.quote(branch)} origin/{shlex.quote(base)}",
            cwd=target_path,
        )
        _ensure_ok(code, out, err, "git checkout feature from origin/base")
    else:
        code, out, err = _run(
            f"git checkout -B {shlex.quote(branch)} {shlex.quote(base)}",
            cwd=target_path,
        )
        _ensure_ok(code, out, err, "git checkout feature from local base")

    code, out, err = _run("git rev-parse --abbrev-ref HEAD", cwd=target_path)
    _ensure_ok(code, out, err, "git rev-parse HEAD")
    if out.strip() != branch:
        raise RuntimeError(f"Not on expected branch: got '{out.strip()}', wanted '{branch}'")

# ---------------------------------------------------------------------------
# File IO into the local clone
# ---------------------------------------------------------------------------

def write_files(target_path: Path, files: List[Dict[str, str]]) -> None:
    """
    Write given file payloads into the Git working tree rooted at target_path.
    Each item: {"path": <repo-relative>, "content": <text>}
    """
    for f in files:
        p = target_path / f["path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(f["content"])
            fh.flush()
            os.fsync(fh.fileno())
        print(f"[write_files] wrote {p} ({p.stat().st_size} bytes)")

# ---------------------------------------------------------------------------
# Commit / Push / PR
# ---------------------------------------------------------------------------

def commit_all(target_path: Path, message: str, author: Optional[str] = None) -> None:
    code, out, err = _run("git add -A", cwd=target_path)
    _ensure_ok(code, out, err, "git add")

    cmd = f'git commit -m {shlex.quote(message)}'
    if author:
        cmd += f' --author {shlex.quote(author)}'
    code, out, err = _run(cmd, cwd=target_path)

    nothing = "nothing to commit" in (out + err).lower()
    if code != 0 and not nothing:
        raise RuntimeError(f"git commit failed: {err or out}")
    if nothing:
        raise RuntimeError("No changes to commit; nothing to push. Did you write any files?")

def push_branch(target_path: Path, branch: str) -> None:
    code, out, err = _run(f"git push -u origin HEAD:refs/heads/{shlex.quote(branch)}", cwd=target_path)
    if code != 0:
        raise RuntimeError(f"git push failed: {err or out}")

def open_pr(
    owner_repo: str,
    head_branch: str,
    base_branch: str,
    title: str,
    body: str,
    token: str,
) -> Dict[str, Any]:
    """
    Create (or retrieve) a PR from head_branch into base_branch.
    Uses explicit 'OWNER:BRANCH' for head; if a PR already exists (422), returns it.
    """
    owner, repo = owner_repo.split("/", 1)
    head_ref = f"{owner}:{head_branch}"

    try:
        pr = _gh_api(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            token,
            data={
                "title": title,
                "head": head_ref,
                "base": base_branch,
                "body": body,
                "maintainer_can_modify": True,
            },
        )
        return pr
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        text = e.response.text if e.response is not None else ""
        msg = f"GitHub PR create failed (status={status}): {text}"

        if status == 422:
            # try open
            try:
                prs = _gh_api(
                    "GET",
                    f"/repos/{owner}/{repo}/pulls",
                    token,
                    params={"head": head_ref, "state": "open"},
                )
            except requests.HTTPError:
                prs = []
            if isinstance(prs, list) and prs:
                return prs[0]

            # try all
            try:
                prs_all = _gh_api(
                    "GET",
                    f"/repos/{owner}/{repo}/pulls",
                    token,
                    params={"head": head_ref, "state": "all"},
                )
            except requests.HTTPError:
                prs_all = []
            if isinstance(prs_all, list) and prs_all:
                prs_all.sort(key=lambda p: p.get("number", 0), reverse=True)
                return prs_all[0]

            # Inspect for "No commits between base and head"
            try:
                j = e.response.json()
                errors = j.get("errors") or []
                if any("No commits between" in (er.get("message", "")) for er in errors if isinstance(er, dict)):
                    raise RuntimeError(
                        f"No commits between base '{base_branch}' and head '{head_ref}'. "
                        f"Ensure commits exist and were pushed to 'origin {head_branch}'."
                    ) from None
            except Exception:
                pass

        raise RuntimeError(msg) from None

# ---------------------------------------------------------------------------
# CI convenience (optional)
# ---------------------------------------------------------------------------

def ensure_actions_workflow(target_path: Path) -> None:
    wf = target_path / ".github" / "workflows" / "agent-ci.yml"
    if wf.exists():
        return
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text(
        """name: agent-ci
on:
  pull_request:
    branches: [ "main" ]
    paths:
      - "**/*.py"
      - "tests/**"
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
          if [ -f test-requirements.txt ]; then pip install -r test-requirements.txt; fi
          pip install pytest
      - name: Run tests
        run: pytest -q
""",
        encoding="utf-8",
    )

# ---------------------------------------------------------------------------
# LOCAL → Repo mapping (using allow-list)
# ---------------------------------------------------------------------------

def prepare_files_from_local(task_id: str) -> List[Dict[str, str]]:
    """
    LOCAL → repo mapping:
      GIT_LOCAL_REPO_PATH/{src,tests,meta,...}  →
      REPO_GENERATED_DIR/<taskId>/{src,tests,meta,...}

    So for example:
      /workspaces/agent-mvp/src/foo.py
        → generated/<taskId>/src/foo.py (inside the GitHub repo clone)
    """
    cfg = load_config()
    local_repo = Path(cfg["LOCAL_REPO_PATH"]).resolve()    # ABSOLUTE path to your local working repo
    repo_rel_prefix = Path(cfg["REPO_GENERATED_DIR"])   # repo-relative destination root

    if not local_repo.exists():
        raise FileNotFoundError(f"Local repo path {local_repo} does not exist")

    allowed_dirs = ["src", "tests", "meta"]
    out: List[Dict[str, str]] = []

    for subdir in allowed_dirs:
        base_dir = local_repo / subdir
        if not base_dir.exists():
            continue
        for src in base_dir.rglob("*"):
            if src.is_file():
                rel = src.relative_to(local_repo)  # keep subdir (e.g., "src/foo.py")
                dst_repo_rel = repo_rel_prefix / rel
                out.append({
                    "path": str(dst_repo_rel),
                    "content": src.read_text(encoding="utf-8"),
                })
                print(f"[prepare_files_from_local] staged {src} → {dst_repo_rel}")

    if not out:
        raise RuntimeError(f"No files found under {local_repo}/{{src,tests,meta}}")

    return out

# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def prepare_repo_and_pr(
    task_id: str,
    design: Dict[str, Any],
    impl: Dict[str, Any],
    tests: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Full flow:
      - Ensure local clone (GIT_LOCAL_REPO_PATH) exists and points to GITHUB_REPO.
      - Checkout base and feature branches.
      - Build file payloads (impl/tests, else LOCAL fallback).
      - Write into local clone under generated/<taskId>/.
      - Commit, push, and open PR.
    """
    cfg = load_config()

    owner_repo = cfg["GITHUB_REPO"]                     # "owner/repo"
    token = cfg["GITHUB_TOKEN"]
    base = cfg["GIT_BASE"]
    local_repo_path = cfg["LOCAL_REPO_PATH"]

    remote_url = cfg["TARGET_REPO_URL"] or f"https://github.com/{owner_repo}.git"
    auth_url = f"https://{token}@github.com/{owner_repo}.git"  # tokenized push URL

    repo_path = Path(cfg["GIT_LOCAL_REPO_PATH"]).resolve()     # local clone folder

    print(f"[prepare] repo={owner_repo} local={repo_path} task={task_id} base={base}")

    if not owner_repo or not token:
        raise RuntimeError("GITHUB_REPO and GITHUB_TOKEN must be set")

    ensure_repo(repo_path, remote_url)
    ensure_remote(repo_path, auth_url)
    checkout_base(repo_path, base)

    branch = f"task/{task_id}"
    checkout_feature(repo_path, branch, base)

    # Build file list: prefer explicit impl/tests, else read from LOCAL.
    files: List[Dict[str, str]] = []
    files += (impl.get("files") or [])
    files += (tests.get("test_files") or [])

    if not files:
        files = prepare_files_from_local(task_id)

    print(f"[prepare] files to write: {len(files)}")
    if not files:
        raise RuntimeError("No files found to write (impl/tests empty and LOCAL folder missing)")

    # ⬇️ Rewrite all paths to be under generated/<taskId>
    adjusted_files: List[Dict[str, str]] = []
    for f in files:
        orig_path = Path(f["path"])
        # ensure generated/<taskId>/…/<original path>
        new_path = Path("generated") / task_id / orig_path
        adjusted_files.append({
            "path": str(new_path),
            "content": f["content"],
        })
        print(f"[prepare] staging {orig_path} → {new_path}")

    write_files(repo_path, adjusted_files)

    # Quick visibility before committing
    code, out, err = _run("git status --porcelain", cwd=repo_path)
    print("[git status]", out or "(clean)")

    ensure_actions_workflow(repo_path)
    commit_all(repo_path, f"Task {task_id}: implement + tests\n\n{design.get('design_summary','')}")
    push_branch(repo_path, branch)

    code, out, _ = _run("git rev-parse HEAD", cwd=repo_path)
    head_sha = out.strip() if code == 0 else ""

    pr = open_pr(
        owner_repo,
        branch,
        base,
        f"Agent Task {task_id}",
        "Automated PR by agent orchestrator.",
        token,
    )

    return {
        "repo": owner_repo,
        "pr_url": pr.get("html_url"),
        "pr_number": pr.get("number"),
        "head_sha": head_sha,
        "head_ref": branch,
    }