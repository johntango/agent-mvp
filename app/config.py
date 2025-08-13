import os
# add/ensure:
import os
import sys
from pathlib import Path

def load_config():
    GITHUB_TOKEN = os.environ["CODE_GEN_KEY"]
    print("ZZZZZZZZZZZ ", GITHUB_TOKEN)
    return {
        "GITHUB_TOKEN": GITHUB_TOKEN,
        "DATA_DIR": os.getenv("DATA_DIR", "./data"),
        "REPORTS_PATH": os.getenv("REPORTS_PATH", "./data/reports.jsonl"),
        "REDPANDA_BROKERS": os.getenv("REDPANDA_BROKERS", "127.0.0.1:9092"),
        "TASK_TOPIC": os.getenv("TASK_TOPIC", "agent_tasks"),
        "REPORT_TOPIC": os.getenv("REPORT_TOPIC", "agent_reports"),
        "STEP_REQUESTS_TOPIC": os.getenv("STEP_REQUESTS_TOPIC", "step_requests"),
        "STEP_RESULTS_TOPIC": os.getenv("STEP_RESULTS_TOPIC", "step_results"),
        "DLQ_TOPIC": os.getenv("DLQ_TOPIC", "dlq"),
        "BACKOFF_S": os.getenv("BACKOFF_S", "5,10,30"),
        "MAX_ATTEMPTS": int(os.getenv("MAX_ATTEMPTS", "3")),
        "LEASE_TTL_S": int(os.getenv("LEASE_TTL_S", "1200")),

        # New GitHub integration config
        "GITHUB_REPO": os.getenv("GITHUB_REPO", "johntango/autoGenCode"),
        "GIT_BASE": os.getenv("GIT_BASE", "main"),
        "TARGET_REPO_URL": os.getenv("TARGET_REPO_URL", "https://github.com/johntango/autoGenCode.git"),
        "TARGET_REPO_PATH": os.getenv("TARGET_REPO_PATH", "./autoGenCode"),
        "GITHUB_PAT": os.environ["CODE_GEN_KEY"],  # optional personal access token for push
        "STATE_DB": os.getenv("STATE_DB", "./data/state.sqlite"),
        # extermal services
        "CI_WATCH_TOPIC": os.getenv("CI_WATCH_TOPIC", "ci_watch"),
        # faust web dashboard port (overridden per-process via env)
        "WEB_PORT": int(os.getenv("WEB_PORT", "6066")),
    }