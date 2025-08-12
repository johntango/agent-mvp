# app/state.py
import sqlite3, time, json, os, hashlib
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from app.config import load_config

cfg = load_config()
DB_PATH = Path(cfg["STATE_DB"])
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("""
    PRAGMA journal_mode=WAL;
    """)
    # schema
    c.executescript("""
    CREATE TABLE IF NOT EXISTS tasks(
      task_id TEXT PRIMARY KEY,
      prompt  TEXT NOT NULL,
      created_at REAL NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending'
    );

    CREATE TABLE IF NOT EXISTS steps(
      task_id TEXT NOT NULL,
      step_id TEXT NOT NULL,
      status  TEXT NOT NULL,           -- queued|running|ok|fail|retry
      attempt INTEGER NOT NULL DEFAULT 0,
      lease_id TEXT,
      not_before REAL,
      started_at REAL,
      finished_at REAL,
      error TEXT,
      PRIMARY KEY(task_id, step_id)
    );

    CREATE TABLE IF NOT EXISTS artifacts(
      task_id TEXT NOT NULL,
      step_id TEXT NOT NULL,
      attempt INTEGER NOT NULL,
      name TEXT NOT NULL,
      uri  TEXT NOT NULL,
      sha256 TEXT,
      size_bytes INTEGER,
      created_at REAL NOT NULL,
      PRIMARY KEY(task_id, step_id, attempt, name)
    );
    """)
    return c

def now() -> float: return time.time()

def init_task(task_id: str, prompt: str) -> None:
    c = _conn()
    c.execute("INSERT OR IGNORE INTO tasks(task_id,prompt,created_at,status) VALUES(?,?,?,?)",
              (task_id, prompt, now(), "pending"))
    c.commit(); c.close()

def enqueue_step(task_id: str, step_id: str) -> None:
    c = _conn()
    c.execute("""INSERT INTO steps(task_id, step_id, status, attempt)
                 VALUES(?,?, 'queued', 0)
                 ON CONFLICT(task_id,step_id) DO UPDATE SET status='queued'""",
              (task_id, step_id))
    c.commit(); c.close()

def _lease_where() -> str:
    # Allow claim if not running OR lease expired
    return "(status != 'running' OR (started_at IS NOT NULL AND started_at + ? < ?))"

def claim_step(task_id: str, step_id: str, lease_ttl_s: int) -> Optional[Tuple[str, int]]:
    """Set status=running, attempt += 1, assign lease_id if claimable. Returns (lease_id, attempt) or None."""
    c = _conn()
    lease_id = os.urandom(8).hex()
    t = now()
    cur = c.execute("""
        SELECT status, attempt, started_at FROM steps WHERE task_id=? AND step_id=?""",
        (task_id, step_id)).fetchone()
    if not cur:
        c.close(); return None
    can_claim = (cur["status"] != "running") or (cur["started_at"] and (cur["started_at"] + lease_ttl_s) < t)
    if not can_claim:
        c.close(); return None
    c.execute("""
        UPDATE steps SET status='running', attempt=attempt+1, lease_id=?, started_at=?
        WHERE task_id=? AND step_id=?""", (lease_id, t, task_id, step_id))
    c.commit(); c.close()
    return lease_id, (cur["attempt"] + 1)

def finish_step(task_id: str, step_id: str, status: str, error: Optional[str]=None) -> None:
    c = _conn()
    c.execute("""UPDATE steps SET status=?, finished_at=?, error=? WHERE task_id=? AND step_id=?""",
              (status, now(), error, task_id, step_id))
    if status == "ok":
        # update task when review finishes
        if step_id.startswith("review@"):
            c.execute("UPDATE tasks SET status='done' WHERE task_id=?", (task_id,))
    elif status in ("fail",):
        c.execute("UPDATE tasks SET status='fail' WHERE task_id=?", (task_id,))
    c.commit(); c.close()

def schedule_retry(task_id: str, step_id: str, not_before_ts: float) -> None:
    c = _conn()
    c.execute("""UPDATE steps SET status='retry', not_before=? WHERE task_id=? AND step_id=?""",
              (not_before_ts, task_id, step_id))
    c.commit(); c.close()

def record_artifact(task_id: str, step_id: str, attempt: int, name: str, uri: str, size_bytes: int) -> None:
    sha = ""
    try:
        import hashlib
        with open(uri, "rb") as f:
            h = hashlib.sha256()
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
            sha = h.hexdigest()
    except Exception:
        pass
    c = _conn()
    c.execute("""INSERT OR REPLACE INTO artifacts(task_id,step_id,attempt,name,uri,sha256,size_bytes,created_at)
                 VALUES(?,?,?,?,?,?,?,?)""",
              (task_id, step_id, attempt, name, uri, sha, size_bytes, now()))
    c.commit(); c.close()
