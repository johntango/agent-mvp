import os, time, json, logging, requests
from pathlib import Path
from typing import Dict, Any
from app.bus import app, report_topic, make_report, ci_watch
from app.config import load_config

cfg = load_config()
LOG = logging.getLogger("agent-mvp.ci-monitor")
LOGFILE = Path(cfg["DATA_DIR"]) / "reports.jsonl"
LOGFILE.parent.mkdir(parents=True, exist_ok=True)

def _append_report(obj: Dict[str, Any]) -> None:
    with LOGFILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def _gh(method: str, url: str, token: str, params=None) -> Dict[str, Any]:
    r = requests.request(method, url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }, params=params, timeout=30)
    r.raise_for_status()
    return r.json() if r.text else {}

def _poll_actions(owner_repo: str, head_sha: str, branch: str, token: str, timeout_s: int = 1800, interval_s: int = 10) -> str:
    owner, repo = owner_repo.split("/", 1)
    t0 = time.time()
    seen = ""
    while True:
        runs = _gh("GET", f"https://api.github.com/repos/{owner}/{repo}/actions/runs", token,
                   params={"branch": branch, "per_page": 10})
        if isinstance(runs, dict) and runs.get("workflow_runs"):
            for run in runs["workflow_runs"]:
                if run.get("head_sha") == head_sha:
                    status = run.get("status")
                    conclusion = run.get("conclusion")
                    if status == "completed" and conclusion:
                        return conclusion
                    seen = status or seen
                    break
        if time.time() - t0 > timeout_s:
            return "timeout"
        time.sleep(interval_s)

@app.agent(ci_watch)
async def monitor(stream):
    async for msg in stream:
        tid = msg["task_id"]
        owner_repo = msg["repo"]
        sha = msg.get("head_sha", "")
        ref = msg.get("head_ref", "")
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            _append_report({"task_id": tid, "status": "error", "summary": "GITHUB_TOKEN not set; cannot monitor CI"})
            continue

        _append_report({"task_id": tid, "status": "ci_wait", "summary": f"Monitoring PR CI for {ref}@{sha[:7]}…"})
        try:
            conclusion = _poll_actions(owner_repo, sha, ref, token)
            _append_report({"task_id": tid, "status": "ci_done", "summary": f"CI result: {conclusion}"})
            await report_topic.send(key=tid.encode(), value=make_report(tid, "ci", f"CI result: {conclusion}"))
        except Exception as e:
            _append_report({"task_id": tid, "status": "error", "summary": f"CI monitor error: {e}"})

if __name__ == "__main__":
    app.main()
