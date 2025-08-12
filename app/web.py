from flask import Flask, render_template_string, request, redirect, url_for
import os, json, subprocess
from pathlib import Path
from app.config import load_config
from jinja2 import DictLoader

cfg = load_config()
DATA_DIR = Path(cfg.get("DATA_DIR","./data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGFILE = DATA_DIR / "reports.jsonl"

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
  {% for t in tasks %}
    <tr>
      <td><a href="{{ url_for('task_detail', task_id=t.task_id) }}"><code>{{ t.task_id }}</code></a></td>
      <td>{{ t.status }}</td>
      <td>
        <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('task_detail', task_id=t.task_id) }}">Open</a>
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
      task_dir = DATA_DIR / task_id
      artifacts = {s: [] for s in ["design@v1","implement@v1","test@v1","review@v1"]}
      previews = {}
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

    # register base template

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

if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000, debug=True)
