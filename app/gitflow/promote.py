from __future__ import annotations
import json, subprocess
from pathlib import Path
from typing import Iterable
from app.config import load_config

def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=str(cwd), check=True)

def _copy_tree(src: Path, dst: Path) -> list[Path]:
    written: list[Path] = []
    if not src.exists(): return written
    for p in src.rglob("*"):
        tgt = dst / p.relative_to(src)
        if p.is_dir():
            tgt.mkdir(parents=True, exist_ok=True)
        else:
            tgt.parent.mkdir(parents=True, exist_ok=True)
            tgt.write_bytes(p.read_bytes())
            written.append(tgt)
    return written

def _read_story_ref(task_root: Path) -> tuple[str,str] | None:
    refp = task_root / "meta" / "story_ref.json"
    if not refp.exists(): return None
    ref = json.loads(refp.read_text(encoding="utf-8"))
    return ref.get("story_id"), ref.get("story_sha256")

def _publish_story_to_repo(story_id: str) -> list[Path]:
    cfg = load_config()
    # Workspace registry (source)
    src_story = Path(cfg["LOCAL_STORY_ROOT"]) / story_id / "story.json"
    if not src_story.exists():
        raise FileNotFoundError(f"Story not found: {src_story}")
    # Repo meta target
    repo_root = Path(cfg["LOCAL_REPO_PATH"])
    repo_meta_root = repo_root / cfg["REPO_META_STORIES_DIR"] / story_id
    repo_meta_root.mkdir(parents=True, exist_ok=True)
    dst_story = repo_meta_root / "story.json"
    dst_story.write_bytes(src_story.read_bytes())
    return [dst_story]

def promote_to_repo(task_id: str, publish_story: bool = True) -> list[Path]:
    cfg = load_config()
    local_staging = Path(cfg["LOCAL_GENERATED_ROOT"]) / task_id
    repo_root = Path(cfg["LOCAL_REPO_PATH"])
    repo_task = repo_root / cfg["REPO_GENERATED_DIR"] / task_id

    written: list[Path] = []
    for sub in ("src","tests","meta"):
        written += _copy_tree(local_staging / sub, repo_task / sub)

    if publish_story:
        ref = _read_story_ref(local_staging)
        if ref:
            story_id, _ = ref
            written += _publish_story_to_repo(story_id)

    return written

def commit_push_open_pr(task_id: str, base_branch: str | None = None) -> None:
    cfg = load_config()
    repo = Path(cfg["LOCAL_REPO_PATH"])
    base = base_branch or cfg.get("GIT_BASE","main")
    branch = f"feat/{task_id}-promotion"

    _run(["git","fetch","origin",base], cwd=repo)
    _run(["git","checkout","-B",branch,f"origin/{base}"], cwd=repo)
    _run(["git","add","-A"], cwd=repo)

    status = subprocess.run(["git","status","--porcelain"], cwd=str(repo), capture_output=True, text=True)
    if status.stdout.strip() == "":
        print("[promotion] No changes to commit.")
        return

    _run(["git","commit","-m",f"chore(gen): promote {task_id} outputs and publish story"], cwd=repo)
    _run(["git","push","-u","origin",branch], cwd=repo)

    try:
        _run([
            "gh","pr","create",
            "--repo", cfg["GITHUB_REPO"],
            "--base", base,
            "--head", branch,
            "--title", f"Promote {task_id} outputs (+ story publication)",
            "--body",  f"Automated promotion for `{task_id}` including story publication under generated/meta/stories."
        ], cwd=repo)
    except Exception as e:
        print(f"[promotion] PR creation skipped/failed: {e}")