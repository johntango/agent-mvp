# app/maintenance/prune_generated.py
from __future__ import annotations
import argparse, json, shutil, subprocess, sys
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.config import load_config

@dataclass(frozen=True)
class TaskInfo:
    task_id: str
    story_file: Optional[str]
    created_at: datetime        # from meta/story_ref.json or dir mtime
    path: Path                  # absolute path to generated/<taskId> root

def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)

def _parse_iso8601_or_none(s: Optional[str]) -> Optional[datetime]:
    if not s: return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None

def _read_story_ref(task_root: Path) -> Tuple[Optional[str], Optional[datetime]]:
    ref = task_root / "meta" / "story_ref.json"
    if not ref.exists():
        return None, None
    try:
        j = json.loads(ref.read_text(encoding="utf-8"))
        story_file = j.get("story_file")
        ts = _parse_iso8601_or_none(j.get("written_at_utc"))
        return story_file, ts
    except Exception:
        return None, None

def _discover_tasks(root: Path) -> List[TaskInfo]:
    if not root.exists():
        return []
    out: List[TaskInfo] = []
    for p in root.iterdir():
        if not p.is_dir():
            continue
        story_file, ts = _read_story_ref(p)
        if ts is None:
            # fallback to directory mtime if no timestamp
            ts = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        out.append(TaskInfo(task_id=p.name, story_file=story_file, created_at=ts, path=p))
    return out

def _group_by_story(tasks: List[TaskInfo]) -> Dict[str, List[TaskInfo]]:
    # Use explicit story_file value; group tasks with unknown story under "<unknown>"
    groups: Dict[str, List[TaskInfo]] = {}
    for t in tasks:
        key = t.story_file or "<unknown>"
        groups.setdefault(key, []).append(t)
    for k in groups:
        groups[k].sort(key=lambda x: x.created_at, reverse=True)  # newest first
    return groups

def _select_prunable(groups: Dict[str, List[TaskInfo]],
                     keep_per_story: int,
                     min_age_days: Optional[int],
                     only_story: Optional[str]) -> List[TaskInfo]:
    cutoff: Optional[datetime] = None
    if min_age_days and min_age_days > 0:
        cutoff = _now_utc() - timedelta(days=min_age_days)

    prunable: List[TaskInfo] = []
    for story_file, items in groups.items():
        if only_story and story_file != only_story:
            continue
        keep_slice = items[:max(keep_per_story, 0)]
        to_eval = items[max(keep_per_story, 0):]
        for t in to_eval:
            if cutoff and t.created_at >= cutoff:
                # too new → skip pruning
                continue
            prunable.append(t)
    return prunable

# ---------------- Local staging prune ----------------
def prune_local_staging(task_ids: List[str], cfg: Dict[str, str], dry_run: bool) -> List[Path]:
    base = Path(cfg["LOCAL_GENERATED_ROOT"])
    removed: List[Path] = []
    for tid in task_ids:
        p = base / tid
        if p.exists():
            if dry_run:
                print(f"[dry-run] local rm -r {p}")
            else:
                shutil.rmtree(p, ignore_errors=True)
                removed.append(p)
                print(f"[local] removed {p}")
    return removed

# ---------------- Repo prune (with commit) ----------------
def _run(cmd: List[str], cwd: Path) -> Tuple[int, str, str]:
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)
    return proc.returncode, proc.stdout, proc.stderr

def prune_repo_and_commit(task_ids: List[str], cfg: Dict[str, str],
                          branch_prefix: str, open_pr: bool, dry_run: bool) -> Optional[str]:
    repo = Path(cfg["LOCAL_REPO_PATH"])
    if not repo.exists():
        print(f"[repo] local clone missing at {repo}")
        return None

    # Create branch
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    branch = f"{branch_prefix}{ts}"
    base = cfg.get("GIT_BASE", "main")

    cmds = [
        ["git", "fetch", "origin", base],
        ["git", "checkout", "-B", branch, f"origin/{base}"],
    ]
    for c in cmds:
        code, out, err = _run(c, repo)
        if code != 0:
            print(f"[repo] cmd failed: {' '.join(c)}\n{err}")
            return None

    # Remove task directories
    for tid in task_ids:
        rel = Path(cfg["REPO_GENERATED_DIR"]) / tid
        target = repo / rel
        if target.exists():
            if dry_run:
                print(f"[dry-run] git rm -r {rel}")
            else:
                code, out, err = _run(["git", "rm", "-r", str(rel)], repo)
                if code != 0:
                    print(f"[repo] git rm failed for {rel}: {err}")

    if dry_run:
        print("[dry-run] skip commit/push/PR")
        return None

    # Commit + push
    msg = f"chore(prune): remove old generated tasks ({len(task_ids)} dirs)"
    for c in [["git", "commit", "-m", msg], ["git", "push", "-u", "origin", branch]]:
        code, out, err = _run(c, repo)
        if code != 0:
            print(f"[repo] cmd failed: {' '.join(c)}\n{err}")
            return None

    if open_pr:
        # Use gh CLI if available
        code, out, err = _run([
            "gh", "pr", "create",
            "--repo", cfg["GITHUB_REPO"],
            "--base", base,
            "--head", branch,
            "--title", "Prune old generated task outputs",
            "--body",  "Automated cleanup of generated/<taskId> directories."
        ], repo)
        if code == 0:
            print("[repo] PR opened")
        else:
            print(f"[repo] PR creation failed (non-fatal): {err}")
    else:
        print("[repo] pushed branch without PR (open manually if desired)")
    return branch

# ---------------- CLI ----------------
def main() -> None:
    cfg = load_config()
    ap = argparse.ArgumentParser(prog="prune-generated",
                                 description="Prune old generated/<taskId> directories locally and in the repo clone.")
    ap.add_argument("--keep-per-story", type=int, default=1,
                    help="Keep this many newest tasks per story file (default: 1).")
    ap.add_argument("--min-age-days", type=int, default=0,
                    help="Protect tasks newer than N days from pruning (default: 0 = no protection).")
    ap.add_argument("--story-file", default=None,
                    help="Prune only tasks associated with this story filename (exact match).")
    ap.add_argument("--scope", choices=["local", "repo", "both"], default="both",
                    help="Where to prune (default: both).")
    ap.add_argument("--open-pr", action="store_true",
                    help="Open a PR after pruning the repo (requires gh CLI auth).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Do not delete, just print what would be done.")

    args = ap.parse_args()

    # Discover local staging tasks (source of truth for mapping task→story)
    local_root = Path(cfg["LOCAL_GENERATED_ROOT"])
    tasks = _discover_tasks(local_root)
    groups = _group_by_story(tasks)
    prunable = _select_prunable(groups, args.keep_per_story, args.min_age_days, args.story_file)

    if not prunable:
        print("Nothing to prune.")
        return

    print("Prunable tasks:")
    for t in prunable:
        print(f"  - {t.task_id}  story={t.story_file or '<unknown>'}  created={t.created_at.isoformat()}")

    tids = [t.task_id for t in prunable]

    if args.scope in ("local", "both"):
        prune_local_staging(tids, cfg, args.dry_run)

    if args.scope in ("repo", "both"):
        prune_repo_and_commit(tids, cfg, branch_prefix="chore/prune-generated-", open_pr=args.open_pr, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
