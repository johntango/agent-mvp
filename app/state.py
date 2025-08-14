# app/state.py
from __future__ import annotations
import sqlite3, time, json, os, hashlib
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from app.config import load_config

from datetime import datetime

cfg = load_config()
DB_PATH = Path(cfg["STATE_DB"])
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def now() -> float: return time.time()

# app/state.py  (add/extend)
# ...existing imports and DB_PATH/_conn()...
# app/state.py (additions)


def _repo_root() -> Path:
    # Works when __file__ exists and when launched from various cwd's.
    if "__file__" in globals():
        return Path(__file__).resolve().parents[1]
    cwd = Path().resolve()
    for p in [cwd, *cwd.parents]:
        if (p / ".git").exists() or (p / "pyproject.toml").exists():
            return p
    return cwd

def fetch_steps(task_id: str) -> List[Dict]:
    c = _conn()
    rows = c.execute(
        "SELECT step_id, status, attempt FROM steps WHERE task_id=? ORDER BY step_id ASC",
        (task_id,),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]

def fetch_step_deps(task_id: str) -> List[Tuple[str, str]]:
    """Returns list of (depends_on, step_id) edges."""
    c = _conn()
    rows = c.execute(
        "SELECT depends_on, step_id FROM step_deps WHERE task_id=?",
        (task_id,),
    ).fetchall()
    c.close()
    return [(r["depends_on"], r["step_id"]) for r in rows]

def _ensure_schema(c: sqlite3.Connection) -> None:
   c.executescript("""
    PRAGMA foreign_keys = ON;

    -- Canonical tasks table (align with rest of code: default 'queued', keep updated_at)
    CREATE TABLE IF NOT EXISTS tasks(
      task_id    TEXT PRIMARY KEY,
      prompt     TEXT NOT NULL,
      created_at TEXT NOT NULL,
      status     TEXT NOT NULL DEFAULT 'queued',
      updated_at TEXT
    );

    CREATE TABLE IF NOT EXISTS task_meta(
      task_id TEXT NOT NULL,
      k       TEXT NOT NULL,
      v       TEXT NOT NULL,
      PRIMARY KEY(task_id, k)
    );

    CREATE TABLE IF NOT EXISTS steps(
      task_id     TEXT NOT NULL,
      step_id     TEXT NOT NULL,
      status      TEXT NOT NULL,           -- queued|running|ok|fail|retry
      attempt     INTEGER NOT NULL DEFAULT 0,
      lease_id    TEXT,
      not_before  REAL,
      started_at  REAL,
      finished_at REAL,
      error       TEXT,
      PRIMARY KEY(task_id, step_id)
    );

    CREATE TABLE IF NOT EXISTS step_deps(
      task_id   TEXT NOT NULL,
      step_id   TEXT NOT NULL,
      depends_on TEXT NOT NULL,
      PRIMARY KEY(task_id, step_id, depends_on)
    );

    CREATE TABLE IF NOT EXISTS artifacts(
      task_id    TEXT NOT NULL,
      step_id    TEXT NOT NULL,
      attempt    INTEGER NOT NULL,
      name       TEXT NOT NULL,
      uri        TEXT NOT NULL,
      sha256     TEXT,
      size_bytes INTEGER,
      created_at REAL NOT NULL,
      PRIMARY KEY(task_id, step_id, attempt, name)
    );

    -- Store the full plan JSON for auditing/debugging
    CREATE TABLE IF NOT EXISTS plans(
      task_id   TEXT PRIMARY KEY,
      plan_json TEXT NOT NULL
    );
    """)

def _conn():
    # Always use configured DB_PATH; return rows addressable by column name
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Pragmas suitable for single-writer/multi-reader patterns
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    # Ensure full schema (including 'plans') exists
    _ensure_schema(conn)
    return conn
    

def save_plan(task_id: str, plan_json: str) -> None:
    c = _conn()
    c.execute("INSERT OR REPLACE INTO plans(task_id, plan_json) VALUES(?,?)", (task_id, plan_json))
    c.commit(); c.close()

def upsert_step(task_id: str, step_id: str) -> None:
    c = _conn()
    c.execute("""INSERT INTO steps(task_id, step_id, status, attempt)
                 VALUES(?,?, 'queued', 0)
                 ON CONFLICT(task_id,step_id) DO UPDATE SET status='queued'""",
              (task_id, step_id))
    c.commit(); c.close()

def add_dependency(task_id: str, step_id: str, depends_on: str) -> None:
    c = _conn()
    c.execute("""INSERT OR IGNORE INTO step_deps(task_id, step_id, depends_on) VALUES(?,?,?)""",
              (task_id, step_id, depends_on))
    c.commit(); c.close()

def deps_satisfied(task_id: str, step_id: str) -> bool:
    c = _conn()
    row = c.execute("""
      SELECT COUNT(*) AS unmet
      FROM step_deps d
      LEFT JOIN steps s2
        ON s2.task_id = d.task_id AND s2.step_id = d.depends_on
      WHERE d.task_id=? AND d.step_id=? AND (s2.status IS NULL OR s2.status != 'ok')
    """, (task_id, step_id)).fetchone()
    c.close()
    return (row["unmet"] == 0)

def list_ready_steps(task_id: str) -> list[str]:
    """Queued steps whose dependencies are all ok."""
    c = _conn()
    rows = c.execute("""
      SELECT s.step_id
      FROM steps s
      WHERE s.task_id=? AND s.status='queued'
      AND NOT EXISTS (
        SELECT 1
        FROM step_deps d
        LEFT JOIN steps s2
          ON s2.task_id=d.task_id AND s2.step_id=d.depends_on
        WHERE d.task_id=s.task_id AND d.step_id=s.step_id
          AND (s2.status IS NULL OR s2.status!='ok')
      )
    """, (task_id,)).fetchall()
    c.close()
    return [r["step_id"] for r in rows]


def init_task(task_id: str, prompt: str) -> None:
    """
    Insert the task row; will create the DB file and schema if missing.
    """
    conn = _conn()
    try:
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        conn.execute(
            "INSERT OR IGNORE INTO tasks(task_id, prompt, created_at, status) VALUES(?,?,?,?)",
            (task_id, prompt, now, "queued"),
        )
    finally:
        conn.close()

    
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

# app/state.py  (additions to publish to GitHub)


def set_meta(task_id: str, k: str, v: str) -> None:
    c = _conn()
    c.execute("INSERT INTO task_meta(task_id,k,v) VALUES(?,?,?) "
              "ON CONFLICT(task_id,k) DO UPDATE SET v=excluded.v",
              (task_id, k, v))
    c.commit(); c.close()

def get_meta(task_id: str, k: str, default: str = "") -> str:
    c = _conn()
    row = c.execute("SELECT v FROM task_meta WHERE task_id=? AND k=?", (task_id, k)).fetchone()
    c.close()
    return row["v"] if row else default

def task_all_ok(task_id: str) -> bool:
    c = _conn()
    row = c.execute("SELECT COUNT(*) AS pending FROM steps WHERE task_id=? AND status!='ok'", (task_id,)).fetchone()
    c.close()
    return (row["pending"] == 0)

def any_steps_remaining(task_id: str) -> bool:
    c = _conn()
    row = c.execute("SELECT COUNT(*) AS n FROM steps WHERE task_id=? AND status IN ('queued','running','retry')", (task_id,)).fetchone()
    c.close()
    return (row["n"] > 0)

   
def update_task_status(task_id: str, status: str) -> None:
    conn = _conn()
    try:
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        conn.execute(
            "UPDATE tasks SET status=?, updated_at=? WHERE task_id=?",
            (status, now, task_id),
        )
    finally:
        conn.close()

def get_task(task_id: str) -> Optional[dict]:
    conn = _conn()
    try:
        cur = conn.execute("SELECT task_id,prompt,created_at,status,updated_at FROM tasks WHERE task_id=?", (task_id,))
        row = cur.fetchone()
        if not row:
            return None
        return {
            "task_id": row[0],
            "prompt": row[1],
            "created_at": row[2],
            "status": row[3],
            "updated_at": row[4],
        }
    finally:
        conn.close()