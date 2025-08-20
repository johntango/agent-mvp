# app/git_integration.py
import os
import shlex
import subprocess
from pathlib import Path
import requests, json
from typing import Any, Dict, List, Optional, Tuple
import fnmatch
import base64
import requests  # pip install requests
from app.config import load_config
import re
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
    "meta/story.json",            # full embedded story (single source of truth)
    "meta/stories/*.json",        # optional extra: original filename snapshot
    "README.md",
]
import base64
from pathlib import Path
from typing import Dict, Any, List

def _text_or_base64_bytes(p: Path) -> Dict[str, str]:
    data = p.read_bytes()
    try:
        return {"content": data.decode("utf-8")}
    except UnicodeDecodeError:
        return {"content": base64.b64encode(data).decode("ascii"), "encoding": "base64"}

def _files_from_impl_payload(impl: Dict[str, Any], design: Dict[str, Any]) -> List[Dict[str, str]]:
    files: List[Dict[str, str]] = []
    # Preferred shapes
    if isinstance(impl.get("files"), list):
        for it in impl["files"]:
            if isinstance(it, dict) and "path" in it and "content" in it:
                files.append({"path": str(it["path"]), "content": it["content"]})
    elif isinstance(impl.get("artifacts"), dict):
        for pth, code in impl["artifacts"].items():
            files.append({"path": str(pth), "content": str(code)})
    # Fallback: code_snippets → single src file; use design.files_touched[0] if present
    if not files:
        snippets = impl.get("code_snippets")
        if isinstance(snippets, list) and snippets:
            fname = None
            ft = design.get("files_touched")
            if isinstance(ft, list) and ft:
                fname = str(ft[0])
            if not fname:
                fname = "src/main.py"
            p = Path(fname)
            if not p.parts or p.parts[0] != "src":
                p = Path("src") / p.name
            if p.suffix == "":
                p = p.with_suffix(".py")
            files.append({"path": str(p), "content": "\n".join(snippets).rstrip() + "\n"})
    return files

def _files_from_tests_payload(tests: Dict[str, Any]) -> List[Dict[str, str]]:
    files: List[Dict[str, str]] = []
    for key in ("files", "test_files"):
        arr = tests.get(key)
        if isinstance(arr, list):
            for it in arr:
                if isinstance(it, dict) and "path" in it and "content" in it:
                    files.append({"path": str(it["path"]), "content": it["content"]})
    cb = tests.get("code_blocks")
    # If you support <path: ...> blocks, parse here (optional)
    return files

def _files_from_local_staging(task_id: str, cfg: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Convert everything under generated/<taskId> into [{path, content}].
    Preserves top-level dir names (src/tests/meta). If your local dir is 'test'
    (singular), it will be kept as 'test/' unless you normalize below.
    """
    files: List[Dict[str, str]] = []
    staging_root = Path(cfg["LOCAL_GENERATED_ROOT"]) / task_id
    if not staging_root.exists():
        return files
    for p in staging_root.rglob("*"):
        p = Path(p)
        if not p.is_file():
            continue
        rel = p.relative_to(staging_root)  # e.g., src/…, tests/…, meta/…
        item = {"path": str(rel)}
        item.update(_text_or_base64_bytes(p))
        files.append(item)
    return files

def _norm_key(path_str: str) -> str:
    # Normalize for dedup (posix-style, case-sensitive; tweak if your FS differs)
    return str(Path(path_str).as_posix())

def _match_any(rel: Path) -> bool:
    s = str(rel).replace("\\", "/")
    return any(fnmatch.fnmatch(s, pat) for pat in ALLOWED_GLOBS)

# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------

def _run(cmd: str | List[str], cwd: Path, env: Optional[dict] = None) -> Tuple[int, str, str]:
    """
    Run a command in 'cwd'. Accepts either a shell-style string or a list of args.
    Returns (exit_code, stdout, stderr) with stdout/stderr stripped.
    """
    e = os.environ.copy()
    if env:
        e.update(env)

    if isinstance(cmd, list):
        args = [str(x) for x in cmd]     # pass through directly
    else:
        args = shlex.split(cmd)          # parse string into argv

    p = subprocess.Popen(
        args,
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

# app/git_integration.py
def checkout_feature(target_path: Path, branch: str, base: str) -> None:
    """
    Ensure we are on <branch>. If origin/<branch> exists, check out from it and
    HARD-RESET local to origin/<branch> so subsequent pushes are fast-forward.
    Otherwise create from origin/<base> (or local <base>) and set tracking.
    """
    # Always fetch first
    code, out, err = _run("git fetch origin --prune", cwd=target_path)
    _ensure_ok(code, out, err, "git fetch")

    # Does the remote feature branch exist?
    code, _, _ = _run(f"git rev-parse --verify remotes/origin/{shlex.quote(branch)}", cwd=target_path)
    if code == 0:
        # Start exactly from the remote branch tip and track it
        code, out, err = _run(
            f"git checkout -B {shlex.quote(branch)} origin/{shlex.quote(branch)}",
            cwd=target_path,
        )
        _ensure_ok(code, out, err, "git checkout origin/branch")
        # Make local identical to remote (prevents non-FF pushes)
        code, out, err = _run(f"git reset --hard origin/{shlex.quote(branch)}", cwd=target_path)
        _ensure_ok(code, out, err, "git reset --hard origin/branch")
    else:
        # Create feature from base
        code2, _, _ = _run(f"git rev-parse --verify remotes/origin/{shlex.quote(base)}", cwd=target_path)
        if code2 == 0:
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

    # Set tracking to the remote branch (ok if remote doesn’t exist yet)
    _run(f"git branch --set-upstream-to=origin/{shlex.quote(branch)} {shlex.quote(branch)}", cwd=target_path)

    # Sanity: ensure we are on <branch>
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
    Stage → repo mapping:
      LOCAL_GENERATED_ROOT/<taskId>/{src,tests,meta}/**/*
        → REPO_GENERATED_DIR/<taskId>/{src,tests,meta}/**/*  (repo-relative)

    Example:
      /workspaces/agent-mvp/generated/abc123/src/foo.py
        → generated/abc123/src/foo.py  (inside the local Git clone)
    """
    cfg = load_config()

    stage_root      = Path(cfg["LOCAL_GENERATED_ROOT"]).resolve() / task_id
    repo_rel_prefix = Path(cfg["REPO_GENERATED_DIR"]) / task_id  # ensure <taskId> is included

    if not stage_root.exists():
        raise FileNotFoundError(f"Stage path not found: {stage_root}")

    out: List[Dict[str, str]] = []
    for sub in ("src", "tests", "meta"):
        base = stage_root / sub
        if not base.exists():
            continue
        for src in base.rglob("*"):
            if src.is_file():
                # keep "src/…", "tests/…", or "meta/…" relative to the <taskId> root
                rel_from_task = src.relative_to(stage_root)
                dst_repo_rel  = repo_rel_prefix / rel_from_task
                out.append({
                    "path": str(dst_repo_rel),
                    "content": src.read_text(encoding="utf-8"),
                })
                print(f"[stage→repo] {src}  →  {dst_repo_rel}")

    if not out:
        raise RuntimeError(f"No files found under {stage_root}/{{src,tests,meta}}")

    return out



# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def _gh_api(method: str, endpoint: str, token: str, data=None, params=None):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    r = requests.request(method, f"https://api.github.com{endpoint}", headers=headers, json=data, params=params, timeout=30)
    r.raise_for_status()
    return r.json() if (r.text or "").strip() else {}

def delete_remote_branch(owner_repo: str, branch: str, token: str) -> None:
    owner, repo = owner_repo.split("/", 1)
    # Delete ref: heads/<branch>
    _gh_api("DELETE", f"/repos/{owner}/{repo}/git/refs/heads/{branch}", token)

def is_pr_merged(owner_repo: str, pr_number: int, token: str) -> bool:
    owner, repo = owner_repo.split("/", 1)
    try:
        _gh_api("GET", f"/repos/{owner}/{repo}/pulls/{pr_number}/merge", token)
        return True  # 204-equivalent; no JSON needed
    except requests.HTTPError as e:
        # 404 means not merged
        return False

def _story_slug_for_task(task_id: str, cfg: dict) -> str | None:
    """
    Try LOCAL_GENERATED_ROOT/<taskId>/meta/story_ref.json first, else None.
    """
    try:
        meta = Path(cfg["LOCAL_GENERATED_ROOT"]) / task_id / "meta" / "story_ref.json"
        if meta.exists():
            j = json.loads(meta.read_text(encoding="utf-8"))
            name = j.get("story_file") or ""
            stem = Path(name).stem
            slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", stem).strip("-")
            return slug or None
    except Exception:
        pass
    return None

def prepare_repo_and_pr(
    task_id: str,
    design: Dict[str, Any],
    impl: Dict[str, Any],
    tests: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Full flow:
      - Ensure local clone exists and points to GITHUB_REPO.
      - Checkout base and feature branches (branch strategy respected).
      - Merge payload (impl/tests) with LOCAL staging (staging wins on conflict).
      - Write into repo under <REPO_GENERATED_DIR>/<taskId>/...
      - Commit (if changes), push, and open PR.
    """
    cfg = load_config()

    owner_repo = cfg["GITHUB_REPO"]                     # "owner/repo"
    token       = cfg["GITHUB_TOKEN"]
    base        = cfg["GIT_BASE"]
    repo_path   = Path(cfg["GIT_LOCAL_REPO_PATH"]).resolve()          # define FIRST
    repo_generated_dir = Path(cfg.get("REPO_GENERATED_DIR") or "generated")
    remote_url  = cfg.get("TARGET_REPO_URL") or f"https://github.com/{owner_repo}.git"
    auth_url    = f"https://{token}@github.com/{owner_repo}.git"

    print(f"[prepare] repo={owner_repo} local={repo_path} task={task_id} base={base}")

    if not owner_repo or not token:
        raise RuntimeError("GITHUB_REPO and GITHUB_TOKEN must be set")

    # Ensure repo and base branch
    ensure_repo(repo_path, remote_url)
    ensure_remote(repo_path, auth_url)
    checkout_base(repo_path, base)

    # Choose branch according to strategy
    strategy = (cfg.get("BRANCH_STRATEGY") or "per_story").lower()
    if strategy == "per_story":
        slug = _story_slug_for_task(task_id, cfg) or task_id
        branch = f"story/{slug}"
    else:
        branch = f"task/{task_id}"

    checkout_feature(repo_path, branch, base)

    # Collect files: payload (impl/tests) + local staging (staging wins)
    payload_files: List[Dict[str, str]] = []
    payload_files += _files_from_impl_payload(impl or {}, design or {})
    payload_files += _files_from_tests_payload(tests or {})
    staged_files = _files_from_local_staging(task_id, cfg)

    merged: Dict[str, Dict[str, str]] = {}
    for f in payload_files:
        merged[_norm_key(f["path"])] = f
    for f in staged_files:
        merged[_norm_key(f["path"])] = f

    files: List[Dict[str, str]] = list(merged.values())
    print(f"[prepare] files to write (payload+staging): {len(files)}")
    for i, f in enumerate(files[:8]):
        print(f"  [{i}] {f['path']} ({'b64' if 'encoding' in f else 'text'})")

    if not files:
        raise RuntimeError("No files found to write (payloads empty and local staging empty)")

    # Rewrite paths into repo tree: <REPO_GENERATED_DIR>/<taskId>/<src|tests|meta>/...
    adjusted_files: List[Dict[str, str]] = []
    for f in files:
        orig_path = Path(f["path"])
        parts = list(orig_path.parts)
        # normalize 'test' → 'tests' (avoid two trees)
        if parts and parts[0] == "test":
            orig_path = Path("tests") / Path(*parts[1:])
        new_path = repo_generated_dir / task_id / orig_path
        item = {"path": str(new_path), "content": f["content"]}
        if "encoding" in f:
            item["encoding"] = f["encoding"]
        adjusted_files.append(item)
        print(f"[prepare] staging {orig_path} → {new_path}")

    # Hard-replace this task’s folder in the repo clone to avoid stale files
    task_root_rel = repo_generated_dir / task_id
    task_root_abs = (repo_path / task_root_rel).resolve()
    if task_root_abs.exists():
        print(f"[prepare] removing existing repo dir {task_root_rel} to avoid stale files")
        shutil.rmtree(task_root_abs, ignore_errors=True)
    _run(["git", "rm", "-r", "--ignore-unmatch", str(task_root_rel)], cwd=repo_path)

    # Write new files into the repo clone
    for f in adjusted_files:
        dest = (repo_path / f["path"]).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        if f.get("encoding") == "base64":
            dest.write_bytes(base64.b64decode(f["content"]))
        else:
            dest.write_text(f["content"], encoding="utf-8")

    # Backfill local staging src/ if empty (keeps staging/repo consistent)
    stage_root = Path(cfg["LOCAL_GENERATED_ROOT"]) / task_id
    stage_src  = stage_root / "src"
    if not stage_src.exists() or not any(stage_src.rglob("*.py")):
        wrote = 0
        for f in adjusted_files:
            p = Path(f["path"])
            try:
                rel_after_task = p.relative_to(repo_generated_dir / task_id)
            except ValueError:
                continue
            if rel_after_task.parts and rel_after_task.parts[0] == "src":
                dest = stage_root / rel_after_task
                dest.parent.mkdir(parents=True, exist_ok=True)
                if f.get("encoding") == "base64":
                    dest.write_bytes(base64.b64decode(f["content"]))
                else:
                    dest.write_text(f["content"], encoding="utf-8")
                wrote += 1
        print(f"[prepare] backfilled {wrote} src file(s) into local staging at {stage_src}")

    # Stage changes
    _run(["git", "add", "-A"], cwd=repo_path)

    # Optional: repo-side test generation (best effort)
    try:
        from app.repo_test_generator import generate_repo_tests_from_story
        generated = generate_repo_tests_from_story(task_id)
        for p in generated:
            print(f"[prepare] added generated test: {p}")
    except FileNotFoundError:
        print(f"[prepare] story.json not found for task {task_id}; skipping test generation")
    except Exception as e:
        print(f"[prepare] test generation failed: {e}")

    # Commit/push/PR
    code, out, err = _run("git status --porcelain", cwd=repo_path)
    print("[git status]", out or "(clean)")
    if not out.strip():
        print("[prepare] no changes detected; skipping commit/push/PR")
        head_sha = _run("git rev-parse HEAD", cwd=repo_path)[1].strip() if _run("git rev-parse HEAD", cwd=repo_path)[0] == 0 else ""
        return {"repo": owner_repo, "pr_url": None, "pr_number": None, "head_sha": head_sha, "head_ref": branch}

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

