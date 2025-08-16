import subprocess
from pathlib import Path
from typing import Dict, List

from app.config import load_config


def _mirror_into_repo(task_id: str, to_copy: Dict[str, List[Path]]) -> Path:
    """
    Mirrors {src,tests,meta} into <repo>/generated/<taskId> (creates missing dirs).
    """
    cfg = load_config()
    repo_root = Path(cfg["GIT_LOCAL_REPO_PATH"])
    task_root = repo_root / cfg["REPO_GENERATED_DIR"] / task_id

    for bucket, files in to_copy.items():
        if not files:
            continue
        out_dir = task_root / bucket
        out_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            rel = f.relative_to((Path(cfg["LOCAL_GENERATED_ROOT"]) / task_id / bucket))
            dest = out_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(f.read_bytes())
    return task_root


def prepare_repo_and_pr(task_id: str, design: str = "", impl: str = "", tests: str = "") -> str:
    """
    Stages mirrored files, commits, pushes, and attempts to open a PR.
    Works whether or not meta/ contains story.json. If nothing to stage, raises.
    """
    cfg = load_config()
    repo_root = Path(cfg["GIT_LOCAL_REPO_PATH"])

    # Collect files from local staging
    from app.gitflow.staging import prepare_files_from_local
    buckets = prepare_files_from_local(task_id)

    # Mirror into repo clone
    task_root = _mirror_into_repo(task_id, buckets)

    # Git add/commit
    def _run(cmd, cwd=repo_root):
        return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True)

    _run(["git", "add", "-A"])
    # Detect nothing to commit
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo_root, text=True, capture_output=True)
    if status.stdout.strip() == "":
        raise RuntimeError("Nothing to commit: no staged changes under the repo clone.")

    msg_lines = [f"chore(gen): promote generated artifacts for task {task_id}"]
    if design:
        msg_lines.append(f"\nDesign:\n{design}")
    if impl:
        msg_lines.append(f"\nImplementation notes:\n{impl}")
    if tests:
        msg_lines.append(f"\nTest notes:\n{tests}")

    _run(["git", "commit", "-m", "\n".join(msg_lines)])
    _run(["git", "push", "origin", cfg["GIT_BASE"]])

    # Attempt PR (optional; requires gh and permissions)
    try:
        _run([
            "gh", "pr", "create",
            "--base", cfg["GIT_BASE"],
            "--title", f"[auto] Generated artifacts for {task_id}",
            "--body", "Automated promotion from agent pipeline.",
        ])
        return "push+pr"
    except Exception:
        # Fallback: pushed branch only
        return "push-only"
