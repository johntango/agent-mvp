import os, subprocess, shlex
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import requests  # pip install requests
from app.config import load_config

def _run(cmd: str, cwd: Path, env: Optional[dict] = None) -> Tuple[int, str, str]:
    e = os.environ.copy()
    if env:
        e.update(env)
    p = subprocess.Popen(shlex.split(cmd), cwd=str(cwd), env=e,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate()
    return p.returncode, out.strip(), err.strip()

def _ensure_ok(code: int, out: str, err: str, ctx: str) -> None:
    if code != 0:
        raise RuntimeError(f"{ctx} failed: {err or out}")

def _gh_api(method: str, endpoint: str, token: str, data: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    url = f"https://api.github.com{endpoint}"
    r = requests.request(method, url, headers=headers, json=data, params=params, timeout=30)
    r.raise_for_status()
    return r.json() if r.text else {}

def ensure_repo(target_path: Path, repo_url: Optional[str]) -> None:
    target_path.mkdir(parents=True, exist_ok=True)
    if not (target_path / ".git").exists():
        if repo_url:
            code, out, err = _run(f"git clone {shlex.quote(repo_url)} .", cwd=target_path)
            if code != 0:
                raise RuntimeError(f"git clone failed: {err or out}")
        else:
            code, out, err = _run("git init", cwd=target_path)
            if code != 0:
                raise RuntimeError(f"git init failed: {err or out}")

def ensure_remote(target_path: Path, repo_https_url_with_auth: str) -> None:
    code, out, err = _run("git remote get-url origin", cwd=target_path)
    if code != 0:
        code, out, err = _run(f"git remote add origin {shlex.quote(repo_https_url_with_auth)}", cwd=target_path)
        _ensure_ok(code, out, err, "git remote add")
    else:
        if out.strip() != repo_https_url_with_auth:
            code, out, err = _run(f"git remote set-url origin {shlex.quote(repo_https_url_with_auth)}", cwd=target_path)
            _ensure_ok(code, out, err, "git remote set-url")

def checkout_base(target_path: Path, base_branch: str) -> None:
    code, out, err = _run("git fetch origin --prune", cwd=target_path)
    _ensure_ok(code, out, err, "git fetch")

    # Does origin/base exist?
    code, out, err = _run(f"git rev-parse --verify origin/{shlex.quote(base_branch)}", cwd=target_path)
    if code == 0:
        # Create/reset local base from remote
        code, out, err = _run(f"git checkout -B {shlex.quote(base_branch)} origin/{shlex.quote(base_branch)}", cwd=target_path)
        _ensure_ok(code, out, err, "git checkout base from origin")
    else:
        # Fall back to local-only (new repo case)
        code, out, err = _run(f"git checkout -B {shlex.quote(base_branch)}", cwd=target_path)
        _ensure_ok(code, out, err, "git checkout local base")



def checkout_feature(target_path: Path, branch: str, base: str) -> None:
    code, out, err = _run("git fetch origin --prune", cwd=target_path)
    _ensure_ok(code, out, err, "git fetch")

    # Prefer creating from origin/base if present
    code, out, err = _run(f"git rev-parse --verify origin/{shlex.quote(base)}", cwd=target_path)
    if code == 0:
        code, out, err = _run(f"git checkout -B {shlex.quote(branch)} origin/{shlex.quote(base)}", cwd=target_path)
        _ensure_ok(code, out, err, "git checkout feature from origin/base")
    else:
        code, out, err = _run(f"git checkout -B {shlex.quote(branch)} {shlex.quote(base)}", cwd=target_path)
        _ensure_ok(code, out, err, "git checkout feature from local base")

    # Sanity check: are we on the branch?
    code, out, err = _run("git rev-parse --abbrev-ref HEAD", cwd=target_path)
    _ensure_ok(code, out, err, "git rev-parse HEAD")
    if out.strip() != branch:
        raise RuntimeError(f"Not on expected branch: got '{out.strip()}', wanted '{branch}'")

def write_files(target_path: Path, files: List[Dict[str, str]]) -> None:
    for f in files:
        p = target_path / f["path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f["content"], encoding="utf-8")


def commit_all(target_path: Path, message: str, author: Optional[str] = None) -> None:
    code, out, err = _run("git add -A", cwd=target_path)
    _ensure_ok(code, out, err, "git add")

    cmd = f'git commit -m {shlex.quote(message)}'
    if author:
        cmd += f' --author {shlex.quote(author)}'
    code, out, err = _run(cmd, cwd=target_path)

    # If nothing to commit, raise early so you know why there’s no ref to push
    nothing = "nothing to commit" in (out + err).lower()
    if code != 0 and not nothing:
        raise RuntimeError(f"git commit failed: {err or out}")
    if nothing:
        raise RuntimeError("No changes to commit; nothing to push. Did you write any files?")


def push_branch(target_path: Path, branch: str) -> None:
    # Push the current HEAD to the remote branch name explicitly.
    code, out, err = _run(f"git push -u origin HEAD:refs/heads/{shlex.quote(branch)}", cwd=target_path)
    if code != 0:
        raise RuntimeError(f"git push failed: {err or out}")
    
def open_pr(owner_repo: str, head_branch: str, base_branch: str, title: str, body: str, token: str) -> Dict[str, Any]:
    owner, repo = owner_repo.split("/", 1)
    # Try create; if exists, fetch existing
    try:
        pr = _gh_api("POST", f"/repos/{owner}/{repo}/pulls", token, {
            "title": title,
            "head": head_branch,
            "base": base_branch,
            "body": body,
            "maintainer_can_modify": True
        })
    except requests.HTTPError:
        prs = _gh_api("GET", f"/repos/{owner}/{repo}/pulls", token, params={"head": f"{owner}:{head_branch}", "state": "open"})
        if isinstance(prs, list) and prs:
            pr = prs[0]
        else:
            raise
    return pr

def ensure_actions_workflow(target_path: Path) -> None:
    wf = target_path / ".github" / "workflows" / "agent-ci.yml"
    if wf.exists():
        return
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text("""name: agent-ci
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
""", encoding="utf-8")

def prepare_repo_and_pr(task_id: str, design: Dict[str, Any], impl: Dict[str, Any], tests: Dict[str, Any]) -> Dict[str, Any]:
    cfg = load_config()  # optio

    owner_repo = cfg["GITHUB_REPO"]            # e.g. johntango/your-repo
    token = cfg["GITHUB_TOKEN"]                 # PAT or fine-grained token (repo scope)
    base = cfg["GIT_BASE"]
    repo_url = cfg["TARGET_REPO_URL"]         # optional
    repo_path = Path(cfg["TARGET_REPO_PATH"]).resolve()

    print(f"ZZZZ Preparing repo {owner_repo} at {repo_path} for task {task_id} for base {base}")

    if not owner_repo or not token:
        raise RuntimeError("GITHUB_REPO and GITHUB_TOKEN must be set")

    https_url = f"https://github.com/{owner_repo}.git"
    auth_url = f"https://{token}:x-oauth-basic@github.com/{owner_repo}.git"

    ensure_repo(repo_path, repo_url or https_url)
    ensure_remote(repo_path, auth_url)
    checkout_base(repo_path, base)

    branch = f"task/{task_id}"
    checkout_feature(repo_path, branch, base)

    files: List[Dict[str, str]] = []
    files += (impl.get("files") or [])
    files += (tests.get("test_files") or [])
    print(f"Files to write: {len(files)}")
    if not files:
        files = prepare_files_from_local(task_id)

    write_files(repo_path, files)
    ensure_actions_workflow(repo_path)
    commit_all(repo_path, f"Task {task_id}: implement + tests\n\n{design.get('design_summary','')}")
    push_branch(repo_path, branch)

    code, out, _ = _run("git rev-parse HEAD", cwd=repo_path)
    head_sha = out.strip() if code == 0 else ""
    pr = open_pr(owner_repo, branch, base, f"Agent Task {task_id}", "Automated PR by agent orchestrator.", token)
    return {
        "repo": owner_repo,
        "pr_url": pr.get("html_url"),
        "pr_number": pr.get("number"),
        "head_sha": head_sha,
        "head_ref": branch,
    }

def prepare_files_from_local(task_id: str) -> List[Dict[str, str]]:
    """
    Read all files under autoCodeGen/generated/<task_id> and return them
    as a list of {"path": <relative_path>, "content": <text>} dicts
    suitable for passing to write_files.
    """
    base_dir = Path("autoGenCode") / "generated" / task_id
    file_entries: List[Dict[str, str]] = []

    if not base_dir.exists():
        raise FileNotFoundError(f"Local path {base_dir} does not exist")

    for file_path in base_dir.rglob("*"):
        if file_path.is_file():
            rel_path = file_path.relative_to(base_dir)  # relative to <task_id>
            with open(file_path, "r", encoding="utf-8") as f:
                contents = f.read()
            file_entries.append({
                # store under generated/<taskId>/… in the repo
                "path": str(Path("generated") / task_id / rel_path),
                "content": contents,
            })

    return file_entries

def prepare(self, params: Dict) -> None:
    # … any setup you need …
    task_id = params["task_id"]
    repo_path = params["repo_path"]

    # load any locally generated files instead of creating hello.py
    files = prepare_files_from_local(task_id)

    # If you still want a dummy file when no files found:
    if not files:
        files = [{
            "path": f"generated/{task_id}/hello.py",
            "content": 'print("Hello from agent")\n',
        }]
        write_files(Path(repo_path), files)

    