from asyncio import events
import app
from flask import Flask, render_template_string, request, redirect, url_for
import os, json, subprocess
from pathlib import Path
from app.config import load_config
from jinja2 import DictLoader
import json, html
from pathlib import Path
from app.state import fetch_steps, fetch_step_deps
from app.task_wrapper import generate_and_publish_task

cfg = load_config()
DATA_DIR = cfg.get("APP_DATA_DIR")
LOGFILE = Path(DATA_DIR) / "reports.jsonl"
STORY_ROOT = Path(cfg["LOCAL_STORY_ROOT"])

HTML_BASE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Agent MVP</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  </head>
  <body class="bg-light">
    <nav class="navbar navbar-expand-lg bg-body-tertiary">
      <div class="container-fluid">
        <a class="navbar-brand" href="{{ url_for('index') }}">Agent MVP</a>
        <div class="collapse navbar-collapse">
          <ul class="navbar-nav me-auto mb-2 mb-lg-0">
            <li class="nav-item"><a class="nav-link" href="{{ url_for('reports') }}">Reports</a></li>
            <li class="nav-item"><a class="nav-link" href="{{ url_for('tasks') }}">Tasks</a></li>
          </ul>
        </div>
      </div>
    </nav>
    <div class="container py-4">
      {% block body %}{% endblock %}
    </div>
  </body>
</html>
"""

HTML_INDEX = """
{% extends "base.html" %}
{% block body %}
<h1 class="mb-3">Enqueue Task</h1>
<div class="card shadow-sm">
  <div class="card-body">
    <form class="row g-2" method="post">
      <div class="col-md-10">
        <input type="text" class="form-control" name="prompt" placeholder="Describe a software task..." required>
      </div>
      <div class="col-md-2 d-grid">
        <button class="btn btn-primary">Enqueue</button>
      </div>
    </form>
  </div>
</div>

<h3 class="mt-4">Recent Reports</h3>
<table class="table table-striped table-hover">
  <thead><tr><th>Task ID</th><th>Status</th><th>Stage</th><th>Summary</th></tr></thead>
  <tbody>
  {% for row in rows %}
    <tr>
      <td><a href="{{ url_for('task_detail', task_id=row.task_id) }}"><code>{{ row.task_id }}</code></a></td>
      <td>{{ row.status }}</td>
      <td>{{ row.get('stage','') }}</td>
      <td style="white-space: pre-wrap">{{ row.summary }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
"""

HTML_REPORTS = """
{% extends "base.html" %}
{% block body %}
<h1>agent_reports (file mirror)</h1>
<p class="text-muted">Showing last {{ rows|length }} entries from <code>{{ logfile }}</code>.</p>
<table class="table table-sm table-striped table-hover">
  <thead><tr><th>ts</th><th>task</th><th>status</th><th>stage</th><th>summary</th></tr></thead>
  <tbody>
  {% for r in rows %}
    <tr>
      <td>{{ r.ts }}</td>
      <td><a href="{{ url_for('task_detail', task_id=r.task_id) }}"><code>{{ r.task_id }}</code></a></td>
      <td>{{ r.status }}</td>
      <td>{{ r.get('stage','') }}</td>
      <td style="white-space: pre-wrap">{{ r.summary }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
"""

HTML_TASKS = """
{% extends "base.html" %}
{% block body %}
<h1>Tasks</h1>

<table class="table table-striped">
  <thead><tr><th>Task ID</th><th>Latest Status</th><th>Actions</th></tr></thead>
  <tbody>
  <h4 class="mt-4">Integration</h4>
      <ul>
        <li>Pull Request: {% if pr_url %}<a href="{{ pr_url }}" target="_blank">{{ pr_url }}</a>{% else %}<span class="text-muted">—</span>{% endif %}</li>
        <li>CI Status: {{ ci_status or "—" }}</li>
      </ul>
  {% for t in tasks %}
  
    <tr>
      <td><a href="{{ url_for('task_detail', task_id=t.task_id) }}"><code>{{ t.task_id }}</code></a></td>
      <td>{{ t.status }}</td>
      <td>
        <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('task_detail', task_id=t.task_id) }}">Open</a>
      </td>
      <td>
        <p>
        <a class="btn btn-sm btn-outline-primary" href="{{ url_for('task_dag', task_id=t.task_id) }}">View DAG</a>
        </p>
      </td>
    </tr>
   
    
  {% endfor %}
  </tbody>
</table>
{% endblock %}
"""

HTML_TASK_DETAIL = """
{% extends "base.html" %}
{% block body %}
<h1>Task <code>{{ task_id }}</code></h1>
<div class="mb-3">
  <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('tasks') }}">Back to tasks</a>
</div>

<h4>Artifacts</h4>
<table class="table table-striped">
  <thead><tr><th>Step</th><th>Files</th><th>Preview</th><th>Replay</th></tr></thead>
  <tbody>
  {% for step in ["design@v1","implement@v1","test@v1","review@v1"] %}
    <tr>
      <td>{{ step }}</td>
      <td>
        {% for f in artifacts.get(step, []) %}
          <div><code>{{ f.name }}</code></div>
        {% endfor %}
      </td>
      <td style="white-space: pre-wrap; max-width: 600px;">
        {% if previews.get(step) %}
          {{ previews[step] }}
        {% else %}
          <span class="text-muted">—</span>
        {% endif %}
      </td>
      <td>
        <form method="post" action="{{ url_for('replay') }}">
          <input type="hidden" name="task_id" value="{{ task_id }}">
          <input type="hidden" name="step_id" value="{{ step }}">
          <input type="text" class="form-control form-control-sm mb-1" name="reason" placeholder="reason (optional)">
          <button class="btn btn-sm btn-primary">Replay {{ step }}</button>
        </form>
      </td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
"""
class StoryPayload(BaseModel):
    story_id: str
    spec: dict

def create_app():

  app = Flask(__name__)
  app.jinja_loader = DictLoader({ "base.html": HTML_BASE,})
    # Jinja templates
  app.jinja_env.globals["base_html"] = HTML_BASE

  @app.route("/", methods=["GET", "POST"])
  def index():
      if request.method == "POST":
          prompt = (request.form.get("prompt") or "").strip()
          if prompt:
              subprocess.Popen(["python", "scripts/enqueue_async.py", "--text", prompt])
      rows = _load_reports(limit=50)
      return render_template_string(HTML_INDEX, rows=rows)


  @app.route("/reports")
  def reports():
      rows = _load_reports(limit=int(request.args.get("n", "200")))
      # simple ts for display
      for r in rows:
          r["ts"] = r.get("ts") or ""
      return render_template_string(HTML_REPORTS, rows=rows, logfile=str(LOGFILE))

  @app.route("/tasks")
  def tasks():
      latest = {}
      for r in _load_reports(limit=5000):  # coarse aggregation
          latest[r["task_id"]] = r["status"]
      items = [{"task_id": k, "status": v} for k, v in latest.items()]
      items.sort(key=lambda x: x["task_id"])
      return render_template_string(HTML_TASKS, tasks=items)

  @app.route("/task/<task_id>")
  def task_detail(task_id: str):
      task_dir = Path(DATA_DIR) / task_id
      artifacts = {s: [] for s in ["design@v1","implement@v1","test@v1","review@v1"]}
      previews = {}
      events = _load_reports_for_task(task_id)
      pr_url = next((e.get("summary","").split("PR: ",1)[-1] for e in events if e.get("status")=="pr_opened"), None)
      ci_status = next((e.get("summary") for e in events if e.get("status")=="ci_done"), None)
      if task_dir.exists():
          for p in sorted(task_dir.glob("*.json")):
              # map to step key
              name = p.name
              step = name.split(".json")[0].split(".attempt")[0]
              artifacts.setdefault(step, []).append({"name": name})
          # load small preview (first ~400 chars)
          for step in artifacts:
              cur = task_dir / f"{step}.json"
              if cur.exists():
                  try:
                      txt = (cur.read_text(encoding="utf-8"))[:400]
                      previews[step] = txt
                  except Exception:
                      pass
      return render_template_string(HTML_TASK_DETAIL, task_id=task_id, artifacts=artifacts, previews=previews)

  @app.route("/replay", methods=["POST"])
  def replay():
    task_id = request.form.get("task_id", "").strip()
    step_id = request.form.get("step_id", "").strip()
    reason  = request.form.get("reason", "").strip()
    if task_id and step_id:
        subprocess.Popen(["python", "scripts/replay_async.py", "--task-id", task_id, "--step", step_id, "--reason", reason])
    return redirect(url_for("task_detail", task_id=task_id))

  @app.route("/api/tasks/<task_id>/dag.json")
  def dag_json(task_id: str):
      steps = fetch_steps(task_id)
      deps  = fetch_step_deps(task_id)
      return {
          "task_id": task_id,
          "nodes": [{"id": s["step_id"], "status": s["status"], "attempt": s["attempt"]} for s in steps],
          "edges": [{"from": a, "to": b} for (a, b) in deps],
      }
    # register base template

  @app.route("/tasks/<task_id>/dag")
  def task_dag(task_id: str):
        cfg = load_config()
        data_dir = Path(cfg["DATA_DIR"])
        # Build Mermaid spec
        mermaid_src = _build_mermaid_for_task(task_id)

        # Simple Bootstrap page with Mermaid
        html_page = """
      <!doctype html>
      <html lang="en">
      <head>
        <meta charset="utf-8">
        <title>DAG · {{ task_id }}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <!-- Bootstrap (unstyled defaults fine for Codespaces) -->
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
        <!-- Mermaid -->
        <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
        <script>
          mermaid.initialize({ startOnLoad: true, theme: 'default', securityLevel: 'loose' });
        </script>
        <style>
          .mermaid { background: #fafafa; border: 1px solid #e5e7eb; border-radius: 0.5rem; padding: 0.75rem; }
          .legend-badge { display:inline-block; width:12px; height:12px; border-radius:3px; margin-right:6px; vertical-align:middle; }
        </style>
      </head>
      <body class="container py-3">
        <h1 class="h4 mb-3">Task DAG <small class="text-muted">({{ task_id }})</small></h1>

        <div class="mb-2">
          <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('task_detail', task_id=task_id) }}">← Back to task</a>
          <a class="btn btn-sm btn-outline-primary" href="{{ url_for('task_dag', task_id=task_id) }}">Refresh</a>
        </div>

        <div class="mb-3">
          <span class="legend-badge" style="background:#eef6ff;border:1px solid #1e90ff"></span> queued
          <span class="legend-badge" style="background:#fff8e1;border:1px solid #f0ad4e"></span> running
          <span class="legend-badge" style="background:#e6ffed;border:1px solid #28a745"></span> ok
          <span class="legend-badge" style="background:#ffeef0;border:1px solid #d73a49"></span> fail
          <span class="legend-badge" style="background:#fff5f5;border:1px solid #dc3545"></span> retry
        </div>

        <div class="mermaid">
      {{ mermaid_src }}
        </div>

        <p class="text-muted mt-3 mb-0">
          Edges reflect <code>depends_on</code>; nodes reflect current status from SQLite.
        </p>
      </body>
      </html>
      """
        return render_template_string(html_page,
                                    task_id=task_id,
                                    mermaid_src=mermaid_src)


  @app.get("/stories/{story_id}")
  def get_story(story_id: str):
      p = STORY_ROOT / f"{story_id}.json"
      if not p.exists():
          raise HTTPException(status_code=404, detail="story not found")
      return json.loads(p.read_text(encoding="utf-8"))

  @app.put("/stories/{story_id}")
  def put_story(story_id: str, payload: StoryPayload | None = None):
      """
      Accept either raw JSON in body (spec), or StoryPayload with .spec.
      """
      # Accept raw dict if client PUTs the spec directly
      if payload is None:
          from fastapi import Request
          # This fallback only works if you wire a Request parameter; keeping simple:
          raise HTTPException(status_code=400, detail="use StoryPayload {story_id, spec}")
      if payload.story_id != story_id:
          raise HTTPException(status_code=400, detail="story_id mismatch")
      STORY_ROOT.mkdir(parents=True, exist_ok=True)
      (STORY_ROOT / f"{story_id}.json").write_text(json.dumps(payload.spec, indent=2), encoding="utf-8")
      return {"ok": True}

  @app.post("/tasks/{task_id}/generate/{story_id}")
  def generate_task(task_id: str, story_id: str):
      try:
          info = generate_and_publish_task(task_id, story_id, design_summary=f"Story={story_id}")
          return {"ok": True, "result": info}
      except FileNotFoundError as e:
          raise HTTPException(status_code=404, detail=str(e))
      except Exception as e:
          raise HTTPException(status_code=500, detail=str(e))
  return app



def _load_reports(limit: int = 200):
    rows = []
    if LOGFILE.exists():
        with LOGFILE.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    rows = rows[-limit:]
    # newest first
    rows.reverse()
    return rows


def _safe_id(s: str) -> str:
    # Mermaid node ids should be simple; keep label separately
    return (
        s.replace(" ", "_")
         .replace("@", "_at_")
         .replace("/", "_")
         .replace("-", "_")
         .replace(".", "_")
    )

def _status_class(status: str) -> str:
    m = {
        "queued": "queued",
        "running": "running",
        "ok": "ok",
        "fail": "fail",
        "retry": "retry",
    }
    return m.get((status or "").lower(), "queued")

def _build_mermaid_for_task(task_id: str) -> str:
    """Returns a Mermaid flowchart string using steps + deps from SQLite."""
    steps = fetch_steps(task_id)
    deps  = fetch_step_deps(task_id)

    if not steps:
        return "flowchart LR\n  note[\"No steps registered for this task\"]"

    lines = ["flowchart LR"]

    # 1) Put classDef BEFORE any nodes (ensures consistent application)
    lines.extend([
        "  classDef queued fill:#eef6ff,stroke:#1e90ff,color:#0b132b,stroke-width:1px;",
        "  classDef running fill:#fff8e1,stroke:#f0ad4e,color:#4a3b00,stroke-width:1px;",
        "  classDef ok fill:#e6ffed,stroke:#28a745,color:#0b3d0b,stroke-width:1px;",
        "  classDef fail fill:#ffeef0,stroke:#d73a49,color:#5a0b14,stroke-width:1px;",
        "  classDef retry fill:#fff5f5,stroke:#dc3545,color:#5a0b14,stroke-width:1px;",
    ])

    # 2) Declare nodes (no class yet)
    node_ids = []
    for s in steps:
        sid = s["step_id"]
        nid = _safe_id(sid)
        status = (s.get("status") or "queued").lower()
        label = f"{sid}\\nstatus: {status}"
        lines.append(f'  {nid}["{label}"]')
        node_ids.append((nid, status))

    # 3) Edges
    for (dep, step) in deps:
        lines.append(f"  {_safe_id(dep)} --> {_safe_id(step)}")

    # 4) Assign classes explicitly (more compatible than :::)
    for nid, status in node_ids:
        cls = _status_class(status)
        lines.append(f"  class {nid} {cls};")

    return "\n".join(lines)

def _load_reports_for_task(task_id: str, limit: int = 1000):
    rows = []
    if LOGFILE.exists():
        with LOGFILE.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("task_id") == task_id:
                    rows.append(obj)
    return rows[-limit:]

if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000, debug=True)
