# app/config.py
import os
from pathlib import Path
from typing import Any, Dict

def _abs(p: str | Path) -> Path:
    """Resolve an absolute path (expands ~, makes absolute, resolves symlinks)."""
    return Path(p).expanduser().resolve()

def load_config() -> Dict[str, Any]:
    # --- Auth (required) -----------------------------------------------------
    token = os.environ["CODE_GEN_KEY"]
    if not token:
        raise KeyError("CODE_GEN_KEY is required in the environment")

    # --- GITHUB (remote) -----------------------------------------------------
    github_repo = os.getenv("GITHUB_REPO", "johntango/autoGenCode")  # owner/repo
    github_base = os.getenv("GIT_BASE", "main")
    github_repo_url = os.getenv("TARGET_REPO_URL", f"https://github.com/{github_repo}.git")

    # --- GIT_LOCAL (local clone of the GitHub repo) --------------------------
    # This directory contains the .git for the *target* repo you push to.
    git_local_repo_path = _abs(os.getenv("GIT_LOCAL_REPO_PATH", "/workspaces/autoGenCode"))

    # --- LOCAL (generator workspace data) ------------------------------------
    # Where your agent writes raw, generated artifacts before they are copied into the repo.
    local_generated_root = _abs(os.getenv("LOCAL_GENERATED_ROOT", "/workspaces/data"))
    
    local_generated_root.mkdir(parents=True, exist_ok=True)
    # Application-local data (DB, logs, UI tails) lives here:
    app_data_dir = _abs(os.getenv("APP_DATA_DIR", "/workspaces/data"))

    # Inside-repo destination prefix for generated files (repo-relative, NOT absolute).
    # Example: "generated" → files land at <GIT_LOCAL>/<generated>/<taskId>/...
    repo_generated_dir = os.getenv("REPO_GENERATED_DIR", "data").strip()
    if Path(repo_generated_dir).is_absolute():
        raise ValueError("REPO_GENERATED_DIR must be a relative path inside the repo (e.g., 'data')")

    # --- Derived files/paths --------------------------------------------------
    reports_path = _abs(os.getenv("REPORTS_PATH", app_data_dir / "reports.jsonl"))
    state_db = _abs(os.getenv("STATE_DB", app_data_dir / "state.sqlite3"))

    # Ensure directories exist
    git_local_repo_path.mkdir(parents=True, exist_ok=True)
    local_generated_root.mkdir(parents=True, exist_ok=True)
    app_data_dir.mkdir(parents=True, exist_ok=True)
    reports_path.parent.mkdir(parents=True, exist_ok=True)
    state_db.parent.mkdir(parents=True, exist_ok=True)


    # --- Streaming/worker knobs ----------------------------------------------
    redpanda = os.getenv("REDPANDA_BROKERS", "127.0.0.1:9092")
    cfg: Dict[str, Any] = {
        # Auth
        "GITHUB_TOKEN": token,                 # used for API calls
        "GITHUB_PAT": token,                   # backward-compat alias if code uses this

        # GITHUB (remote identifiers)
        "GITHUB_REPO": github_repo,            # "owner/repo"
        "GIT_BASE": github_base,               # base branch (e.g., "main")
        "TARGET_REPO_URL": github_repo_url,    # full HTTPS URL to the remote

        # GIT_LOCAL (local clone of the target repo)
        "GIT_LOCAL_REPO_PATH": str(git_local_repo_path),   # preferred key
        "TARGET_REPO_PATH": str(git_local_repo_path),      # backward-compat alias

        # LOCAL (generator workspace)
        "LOCAL_GENERATED_ROOT": str(local_generated_root), # preferred key

        # Where generated files should live *inside the repo* (relative folder)
        "REPO_GENERATED_DIR": repo_generated_dir,
        "GENERATED_DIR": repo_generated_dir,               # backward-compat alias

        # App-local data
        "APP_DATA_DIR": str(app_data_dir),
        "REPORTS_PATH": str(reports_path),
        "STATE_DB": str(state_db),

        # Messaging / worker settings
        "REDPANDA_BROKERS": redpanda,
        "TASK_TOPIC": os.getenv("TASK_TOPIC", "agent_tasks"),
        "REPORT_TOPIC": os.getenv("REPORT_TOPIC", "agent_reports"),
        "STEP_REQUESTS_TOPIC": os.getenv("STEP_REQUESTS_TOPIC", "step_requests"),
        "STEP_RESULTS_TOPIC": os.getenv("STEP_RESULTS_TOPIC", "step_results"),
        "DLQ_TOPIC": os.getenv("DLQ_TOPIC", "dlq"),
        "BACKOFF_S": os.getenv("BACKOFF_S", "5,10,30"),
        "MAX_ATTEMPTS": int(os.getenv("MAX_ATTEMPTS", "3")),
        "LEASE_TTL_S": int(os.getenv("LEASE_TTL_S", "1200")),
        "CI_WATCH_TOPIC": os.getenv("CI_WATCH_TOPIC", "ci_watch"),

        # Web/UI
        "WEB_PORT": int(os.getenv("WEB_PORT", "6066")),
        # NEW (central library of stories, not under taskId)
        "LOCAL_STORY_ROOT": os.getenv("LOCAL_STORY_ROOT", "/workspaces/stories"),  # ABSOLUTE


        # Where to place a snapshot of the story inside each task folder in the repo
        "REPO_STORY_SNAPSHOT_REL": "meta/story.json",  # repo-relative path under <REPO_GENERATED_DIR>/<taskId>/
    }

    return cfg