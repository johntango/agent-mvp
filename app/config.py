# app/config.py
import os
from pathlib import Path
from typing import Dict

def _detect_workspace_root() -> Path:
    # 1) Codespaces sets GITHUB_WORKSPACE to /workspaces/<repo>
    gw = os.getenv("GITHUB_WORKSPACE")
    if gw:
        p = Path(gw).resolve()
        if p.exists():
            return p

    # 2) Allow explicit override
    ow = os.getenv("LOCAL_WORKSPACE_ROOT")
    if ow:
        p = Path(ow).resolve()
        if p.exists():
            return p

    # 3) Infer by scanning upward for repo markers
    here = Path(__file__).resolve()
    for cand in here.parents:
        if (cand / ".git").exists() or (cand / "pyproject.toml").exists():
            return cand

    # 4) Fallback
    return Path.cwd()


def load_config() -> Dict:
    token = os.environ["CODE_GEN_KEY"]  # required

    WORKSPACE_ROOT = _detect_workspace_root()

    # ── Local, non-git operational data (stable) ─────────────────────────────────
    # Keep reports/DB etc. in <workspace>/data by default.
    APP_DATA_DIR = Path(os.getenv("APP_DATA_DIR", WORKSPACE_ROOT / "data")).resolve()

    # ── Local staging area for generated code (step 1 of 2) ─────────────────────
    # *** This is the key change: default to <workspace>/generated ***
    LOCAL_GENERATED_ROOT = Path(
        os.getenv("LOCAL_GENERATED_ROOT", WORKSPACE_ROOT / "generated")
    ).resolve()

    # Canonical stories library (optional, independent of per-task snapshots)
    LOCAL_STORY_ROOT = Path(
        os.getenv("LOCAL_STORY_ROOT", WORKSPACE_ROOT / "stories")
    ).resolve()

    # ── Local git clone that mirrors the GitHub repo (step 2 of 2) ───────────────
    GIT_LOCAL_REPO_PATH = Path(
        os.getenv("GIT_LOCAL_REPO_PATH", WORKSPACE_ROOT / "autoGenCode")
    ).resolve()

    cfg = {
        # Workspace
        "WORKSPACE_ROOT": str(WORKSPACE_ROOT),

        # LOCAL (non-git) paths
        "APP_DATA_DIR": str(APP_DATA_DIR),
        "LOCAL_GENERATED_ROOT": str(LOCAL_GENERATED_ROOT),  # e.g. /workspaces/agent-mvp/generated
        "LOCAL_STORY_ROOT": str(LOCAL_STORY_ROOT),

        # For legacy code that expects this name to point at the *workspace*,
        # keep LOCAL_REPO_PATH aligned with the local clone path (or rename in code).
        "LOCAL_REPO_PATH": str(GIT_LOCAL_REPO_PATH),

        # Files under LOCAL (operational)
        "REPORTS_PATH": str(Path(os.getenv("REPORTS_PATH", APP_DATA_DIR / "reports.jsonl")).resolve()),
        "STATE_DB": str(Path(os.getenv("STATE_DB", APP_DATA_DIR / "state.sqlite3")).resolve()),

        # GitHub / git
        "GITHUB_REPO": os.getenv("GITHUB_REPO", "johntango/autoGenCode"),
        "TARGET_REPO_URL": os.getenv("TARGET_REPO_URL", "https://github.com/johntango/autoGenCode.git"),
        "GIT_LOCAL_REPO_PATH": str(GIT_LOCAL_REPO_PATH),  # e.g. /workspaces/agent-mvp/autoGenCode
        "REPO_GENERATED_DIR": os.getenv("REPO_GENERATED_DIR", "generated"),  # path inside the repo clone
        "GIT_BASE": os.getenv("GIT_BASE", "main"),

        # Runtime topics / params
        "REDPANDA_BROKERS": os.getenv("REDPANDA_BROKERS", "127.0.0.1:9092"),
        "TASK_TOPIC": os.getenv("TASK_TOPIC", "agent_tasks"),
        "REPORT_TOPIC": os.getenv("REPORT_TOPIC", "agent_reports"),
        "STEP_REQUESTS_TOPIC": os.getenv("STEP_REQUESTS_TOPIC", "step_requests"),
        "STEP_RESULTS_TOPIC": os.getenv("STEP_RESULTS_TOPIC", "step_results"),
        "DLQ_TOPIC": os.getenv("DLQ_TOPIC", "dlq"),
        "CI_WATCH_TOPIC": os.getenv("CI_WATCH_TOPIC", "ci_watch"),
        "BACKOFF_S": os.getenv("BACKOFF_S", "5,10,30"),
        "MAX_ATTEMPTS": int(os.getenv("MAX_ATTEMPTS", "3")),
        "LEASE_TTL_S": int(os.getenv("LEASE_TTL_S", "1200")),
        "WEB_PORT": int(os.getenv("WEB_PORT", "6066")),

        # Tokens
        "GITHUB_TOKEN": token,
        "GITHUB_PAT": token,
    }

    # Ensure directories exist
    for key in ("APP_DATA_DIR", "LOCAL_GENERATED_ROOT", "LOCAL_STORY_ROOT", "GIT_LOCAL_REPO_PATH"):
        Path(cfg[key]).mkdir(parents=True, exist_ok=True)
    Path(cfg["REPORTS_PATH"]).parent.mkdir(parents=True, exist_ok=True)
    Path(cfg["STATE_DB"]).parent.mkdir(parents=True, exist_ok=True)

    return cfg
