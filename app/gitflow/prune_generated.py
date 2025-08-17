# app/maintenance/prune_generated.py
from __future__ import annotations

import argparse
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

from app.config import load_config

# ---------- util ----------

def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)

def _run(cmd: List[str], cwd: Path) -> Tuple[int, str, str]:
    p = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)
    return p.returncode, p.stdout, p.stderr

# ---------- discovery ----------

@dataclass(frozen=True)
class TaskInfo:
    task_id: str
    story_file: str | None
    created_at: datetime
    path: Path

def _parse_iso8601_or_none(s: str | None) -> datetime | None:
    if not s: return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None

def _read_story_ref(task_root: Path) -> tuple[str | None, datetime | None]:
    ref = task_root / "meta" / "story_ref.json"
    if not ref.exists(): return None, None
    try:
        j = ref.read_text(encoding="utf-8")
        import json as _json
        obj = _json.loads(j)
        return obj.get("story_file"), _parse_iso8601_or_none(obj.get("written_at_utc"))
    except Exception:
        return None, None

def _discover_tasks(staging_root: Path) -> List[TaskInfo]:
    if not staging_root.exists(): return []
    out: List[TaskInfo] = []
    for p in staging_root.iterdir():
        if not p.is_dir(): continue
        story, ts = _read_story_ref(p)
        if ts is None:
            ts = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        out.append(TaskInfo(task_id=p.name, story_file=story, created_at=ts, path=p))
    return out

def _group_by_story(tasks: List[TaskInfo]) -> Dict[str, List[TaskInfo]]:
    groups: Dict[str, List[TaskInfo]] = {}
    for t in tasks:
        key = t.story_file or "<unknown>"
        groups.setdefault(key, []).append(t)
    for k in groups:
        groups[k].sort(key=lambda x: x.created_at, reverse=True)
    return groups

def _select_prunable(groups: Dict[str, List[TaskInfo]],
                     keep_per_story: int,
                     min_age_days: int,
                     only_story: str | None) -> List[TaskInfo]:
    cutoff = _now_utc() - timedelta(days=min_age_days) if min_age_days > 0 else None
    prunable: List[TaskInfo] = []
    for story, items in groups.items():
        if only_story and story != only_story: continue
        keep_n = max(keep_per_story, 0)
        for t in items[keep_n:]:
            if cutoff and t.created_at >= cutoff:  # too new
                continue
            prunable.append(t)
    return prunable

# ---------- actions ----------

def prune_local_staging(task_ids: List[str], cfg: Dict[str, str], *, dry_run: bool) -> None:
    base = Path(cfg["LOCAL_GENERATED_ROOT"])
    for tid in task_ids:
        p = base / tid
        if p.exists():
            if dry_run:
                print(f"[dry-run] local rm -r {p}")
            else:
                shutil.rmtree(p, ignore_errors=True)
                print(f"[local] removed {p}")

def prune_repo_and_commit(task_ids: List[str], cfg: Dict[str, str],
                          *, branch_prefix: str = "chore/prune-generated-",
                          open_pr: bool = False, dry_run: bool = False) -> str | None:
    repo = Path(cfg.get("GIT_LOCAL_REPO_PATH") or cfg["LOCAL_REPO_PATH"]).resolve()
    if not repo.exists():
        print(f"[repo] local clone missing at {repo}")
        return None

    base = cfg.get("GIT_BASE", "main")
    owner_repo = cfg["GITHUB_REPO"]
    ts_branch = f"{branch_prefix}{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    for cmd in (["git","fetch","origin",base],
                ["git","checkout","-B",ts_branch,f"origin/{base}"]):
        code,out,err = _run(cmd, repo)
        if code != 0:
            print(f"[repo] cmd failed: {' '.join(cmd)}\n{err}")
            return None

    removed_any = False
    for tid in task_ids:
        rel = Path(cfg["REPO_GENERATED_DIR"]) / tid
        target = repo / rel
        if target.exists():
            if dry_run:
                print(f"[dry-run] remove {rel} (fs) and stage deletion")
            else:
                shutil.rmtree(target, ignore_errors=True)
                removed_any = True
        # Stage deletions regardless of current track state
        if dry_run:
            print(f"[dry-run] git rm -r --ignore-unmatch {rel}")
        else:
            _run(["git","rm","-r","--ignore-unmatch",str(rel)], repo)

    if dry_run:
        print("[dry-run] skip commit/push/PR")
        return None

    _run(["git","add","-A"], repo)
    code, out, _ = _run(["git","status","--porcelain"], repo)
    if code != 0 or not out.strip():
        print("[repo] no changes to commit")
        return None

    msg = f"chore(prune): remove old generated tasks ({len(task_ids)} dirs)"
    for cmd in (["git","commit","-m",msg], ["git","push","-u","origin",ts_branch]):
        code,out,err = _run(cmd, repo)
        if code != 0:
            print(f"[repo] cmd failed: {' '.join(cmd)}\n{err}")
            return None

    if open_pr:
        code,out,err = _run([
            "gh","pr","create",
            "--repo", owner_repo,
            "--base", base,
            "--head", ts_branch,
            "--title", "Prune old generated task outputs",
            "--body",  "Automated cleanup of generated/<taskId> directories."
        ], repo)
        if code == 0:
            print("[repo] PR opened")
        else:
            print(f"[repo] PR creation failed (non-fatal): {err}")

    return ts_branch

# ---------- library entrypoint ----------

def run_prune(*, keep_per_story: int = 1, min_age_days: int = 0,
              story_file: str | None = None, scope: str = "both",
              open_pr: bool = False, dry_run: bool = False) -> None:
    """
    Programmatic API: prune local staging and/or repo clone.
    No argparse, no sys.argv.
    """
    cfg = load_config()
    staging_root = Path(cfg["LOCAL_GENERATED_ROOT"])
    tasks = _discover_tasks(staging_root)
    groups = _group_by_story(tasks)
    prunable = _select_prunable(groups, keep_per_story, min_age_days, story_file)

    if not prunable:
        print("Nothing to prune.")
        return

    tids = [t.task_id for t in prunable]
    print(f"[prune] candidates: {tids}")

    if scope in ("local","both"):
        prune_local_staging(tids, cfg, dry_run=dry_run)
    if scope in ("repo","both"):
        prune_repo_and_commit(tids, cfg, open_pr=open_pr, dry_run=dry_run)

# ---------- CLI wrapper (optional) ----------

def main_with_args(argv: List[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="prune-generated")
    parser.add_argument("--keep-per-story", type=int, default=1)
    parser.add_argument("--min-age-days", type=int, default=0)
    parser.add_argument("--story-file", default=None)
    parser.add_argument("--scope", choices=["local","repo","both"], default="both")
    parser.add_argument("--open-pr", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    run_prune(keep_per_story=args.keep_per_story,
              min_age_days=args.min_age_days,
              story_file=args.story_file,
              scope=args.scope,
              open_pr=args.open_pr,
              dry_run=args.dry_run)

if __name__ == "__main__":
    main_with_args()  # uses real sys.argv only when invoked as a script
