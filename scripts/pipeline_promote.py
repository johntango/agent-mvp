from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from app.config import load_config


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    print("$", " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def _copy_tree(src: Path, dst: Path) -> list[Path]:
    written: list[Path] = []
    if not src.exists():
        return written
    for p in src.rglob("*"):
        rel = p.relative_to(src)
        target = dst / rel
        if p.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            data = p.read_bytes()
            target.write_bytes(data)
            written.append(target)
    return written


def promote_to_repo(task_id: str) -> list[Path]:
    cfg = load_config()
    local_staging = Path(cfg["LOCAL_GENERATED_ROOT"]) / task_id
    repo_root = Path(cfg["LOCAL_REPO_PATH"])  # local clone path
    repo_generated = repo_root / cfg["REPO_GENERATED_DIR"] / task_id

    # Ensure repo clone exists (assumed cloned already by upstream step)
    if not repo_root.exists():
        raise FileNotFoundError(f"Local repo clone not found at {repo_root}")

    # Sync directories: src/, tests/, meta/
    written: list[Path] = []
    for sub in ("src", "tests", "meta"):
        written += _copy_tree(local_staging / sub, repo_generated / sub)

    return written


def commit_push_open_pr(task_id: str, *, branch_prefix: str = "feat/tests-") -> None:
    cfg = load_config()
    repo = Path(cfg["LOCAL_REPO_PATH"])  # same as GIT_LOCAL_REPO_PATH
    base = cfg.get("GIT_BASE", "main")
    branch = f"{branch_prefix}{task_id}"

    # Configure git user if missing (Codespaces often sets these, but ensure)
    _run(["git", "config", "user.name", os.getenv("GIT_AUTHOR_NAME", "codespaces-bot")], cwd=repo)
    _run(["git", "config", "user.email", os.getenv("GIT_AUTHOR_EMAIL", "codespaces@users.noreply.github.com")], cwd=repo)

    # Create branch
    _run(["git", "fetch", "origin", base], cwd=repo)
    _run(["git", "checkout", "-B", branch, f"origin/{base}"], cwd=repo)

    # Add and commit
    _run(["git", "add", "-A"], cwd=repo)
    # If nothing to commit, `git commit` will exit non-zero; guard by `--allow-empty`? Prefer explicit check
    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(repo), capture_output=True, text=True)
    if status.stdout.strip() == "":
        print("[promotion] No changes detected; skipping commit/push/PR.")
        return

    _run(["git", "commit", "-m", f"test(gen): add generated tests for {task_id}"] , cwd=repo)
    _run(["git", "push", "-u", "origin", branch], cwd=repo)

    # Create PR via gh CLI if present; fallback to API is possible but gh is simplest in Codespaces
    # Requires: `gh auth status` with GITHUB_TOKEN. Codespaces typically injects it.
    try:
        _run([
            "gh", "pr", "create",
            "--repo", cfg["GITHUB_REPO"],
            "--base", base,
            "--head", branch,
            "--title", f"Add generated tests for {task_id}",
            "--body", f"Automated promotion of staged tests for `{task_id}`." ,
        ], cwd=repo)
    except subprocess.CalledProcessError as e:
        print(f"[promotion] Failed to open PR via gh: {e}. You can open manually.")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Promote staged files and open PR")
    ap.add_argument("task_id")
    args = ap.parse_args()

    written = promote_to_repo(args.task_id)
    print(f"[promotion] synced {len(written)} files to repo clone")
    commit_push_open_pr(args.task_id)