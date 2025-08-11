from flask import Flask, render_template_string, request
import os, json, subprocess
from pathlib import Path
from app.config import load_config

cfg = load_config()
Path(cfg["DATA_DIR"]).mkdir(parents=True, exist_ok=True)
LOGFILE = os.path.join(cfg["DATA_DIR"], "reports.jsonl")

HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Agent MVP Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  </head>
  <body class="bg-light">
    <div class="container py-4">
      <h1 class="mb-4">Agent MVP Dashboard</h1>
      <div class="card shadow-sm">
        <div class="card-body">
          <form class="row g-2" method="post">
            <div class="col-md-10">
              <input type="text" class="form-control" name="prompt" placeholder="Describe a software task..." required>
            </div>
            <div class="col-md-2 d-grid">
              <button class="btn btn-primary">Enqueue Task</button>
            </div>
          </form>
        </div>
      </div>
      <div class="mt-4">
        <h3>Reports</h3>
        <table class="table table-striped table-hover">
          <thead><tr><th>Task ID</th><th>Status</th><th>Summary</th></tr></thead>
          <tbody>
          {% for row in rows %}
            <tr>
              <td><code>{{ row.task_id }}</code></td>
              <td>{{ row.status }}</td>
              <td style="white-space: pre-wrap">{{ row.summary }}</td>
            </tr>
          {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </body>
</html>
"""

def create_app():
    app = Flask(__name__)

    @app.route("/", methods=["GET", "POST"])
    def index():
        rows = []
        if os.path.exists(LOGFILE):
            with open(LOGFILE, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        rows.append(json.loads(line))
                    except:
                        pass
            rows = list(reversed(rows))[:50]

        if request.method == "POST":
            prompt = request.form.get("prompt","").strip()
            if prompt:
                subprocess.Popen(["python", "scripts/enqueue.py", "--text", prompt])
        return render_template_string(HTML, rows=rows)

    return app

if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000, debug=True)
