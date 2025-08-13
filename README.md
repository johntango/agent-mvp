# Agent-MVP (Faust/Redpanda + OpenAI Agents + Flask UI)

link to https://docs.google.com/document/d/1q3a472cCyPQLtxxhxXWPkCHUrTHQ31YcaKtW77orbfs/edit?usp=sharing 

A minimal yet extensible multi-agent system that accepts natural-language software tasks, executes a four-stage pipeline (Design → Implement → Test → Review), persists artifacts, and exposes a small Bootstrap UI for enqueuing tasks, inspecting reports, and replaying individual agent steps.

This README documents architecture, data flow, configuration, operation, and troubleshooting.
----

# 0) Start Redpanda (as you already do)
docker rm -f redpanda 2>/dev/null || true
docker run -d --name=redpanda \
  -p 9092:9092 -p 9644:9644 \
  redpandadata/redpanda:v24.3.18 \
  redpanda start --overprovisioned --smp 1 --memory 1G --reserve-memory 0M \
  --node-id 0 --check=false \
  --kafka-addr PLAINTEXT://0.0.0.0:9092 \
  --advertise-kafka-addr PLAINTEXT://127.0.0.1:9092

# 1) Start services (each in its own terminal from repo root)
export REDPANDA_BROKERS=127.0.0.1:9092
export DATA_DIR=./data
make planner
make worker
make orchestrator
make web    # open http://localhost:5000

# 2) Enqueue a task
make send TEXT="Write a tiny Python program that prints 'Hello Earthling'"

# 3) Inspect artifacts
tail -n 50 ./data/reports.jsonl     # (planner writes 'received'; orchestrator writes 'done' on completion)
ls -la ./data/<task_id>             # design@v1.json, implement@v1.json, test@v1.json, review@v1.json
sqlite3 ./data/state.sqlite '.schema' '.tables'

---

## 1. Architecture
| Topic (env var)                             | Purpose                                           | Producers (write)                                                                               | Consumers (subscribe)                                                |
| ------------------------------------------- | ------------------------------------------------- | ----------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| **`agent_tasks`** (`TASK_TOPIC`)            | New tasks & replay commands                       | `scripts/enqueue_async.py` (UI + CLI), `scripts/replay_async.py`                                | **Planner** (`app/planner_service.py`)                               |
| **`step_requests`** (`STEP_REQUESTS_TOPIC`) | Work items for a specific pipeline step           | **Planner** (initial `design@v1`), **Orchestrator** (next steps, retries)                       | **Worker** (`app/worker.py`)                                         |
| **`step_results`** (`STEP_RESULTS_TOPIC`)   | Results from a single step (ok/fail)              | **Worker**                                                                                      | **Orchestrator** (`app/orchestrator_service.py`)                     |
| **`agent_reports`** (`REPORT_TOPIC`)        | Human-friendly status events                      | **Planner** (`received`), **Orchestrator** (`done`, `error`, `pr`, `ci`), **CI Monitor** (`ci`) | (none in code today; the **UI** reads `./data/reports.jsonl` mirror) |
| **`ci_watch`** (`CI_WATCH_TOPIC`)           | Ask CI monitor to watch a PR/branch               | **Orchestrator** (after opening PR)                                                             | **CI Monitor** (`app/ci_monitor_service.py`)                         |
| **`agent_dlq`** (`DLQ_TOPIC`)               | Dead-letter queue for steps that exceeded retries | **Orchestrator**                                                                                | (none yet — future ops/alerting consumer)                            |

### Components

- **Message bus:** Redpanda (Kafka API compatible).
- **Stream processor:** Faust (`app/worker.py`) consuming `agent_tasks`, producing `agent_reports`, and writing local logs/artifacts.
- **Agents:** Factory functions (no classes) using the OpenAI Agents SDK:

  - `Architect`, `Implementer`, `Tester`, `Reviewer` with typed Pydantic outputs.

- **Producers:**

  - `scripts/enqueue_async.py` — enqueue a new task (aiokafka).
  - `scripts/replay_async.py` — request replay of a single step for an existing task (aiokafka).

- **Web UI:** Flask + Bootstrap (`app/web.py`) with routes:

  - `/` enqueue form + recent reports,
  - `/reports` view of `agent_reports` mirror (from file),
  - `/tasks` task list,
  - `/task/<task_id>` task detail + **Replay** buttons.

### Topics

- **`agent_tasks`** (input): receives JSON task requests and replay commands.
- **`agent_reports`** (output): receives status/report events. The worker also mirrors a subset to a local file for the UI.

### Persistence (file-based for debugging)

- **Append-only report log:** `./data/reports.jsonl` (one JSON record per line).
- **Per-task artifacts:** `./data/<task_id>/design@v1.json`, `implement@v1.json`, `test@v1.json`, `review@v1.json`.
  Replays produce versioned copies: `.../step.attemptN.json` and update the canonical `step.json`.

> A SQLite state store can be introduced later without changing the topic schema.

---

## 2. Data contracts (JSON)

### 2.1 Task (enqueue)

```json
{
  "task_id": "UUIDv4",
  "prompt": "Write a tiny Python program that prints 'Hello Earthling'"
}
```

### 2.2 Replay request (sent to the same `agent_tasks` topic)

```json
{
  "action": "replay_step",
  "task_id": "UUIDv4",
  "step_id": "design@v1 | implement@v1 | test@v1 | review@v1",
  "reason": "Optional note"
}
```

### 2.3 Report events (published to `agent_reports` and mirrored to file)

Minimal shape (actual content may include additional fields):

```json
{ "task_id": "UUIDv4", "status": "received",    "summary": "..." }
{ "task_id": "UUIDv4", "status": "stage_done", "stage": "design@v1", "summary": "Design completed" }
{ "task_id": "UUIDv4", "status": "done",       "summary": "Task completed; artifacts in ./data/<task_id>" }
{ "task_id": "UUIDv4", "status": "error",      "summary": "error: <message>" }
{ "task_id": "UUIDv4", "status": "replayed",   "summary": "Implement replayed (attempt 2)" }
```

### 2.4 Agent outputs (Pydantic → JSON)

- **Design**

  ```json
  { "design_summary": "...", "files_touched": ["path/to/file.py", "..."] }
  ```

- **Implementation**

  ```json
  { "diff_summary": "...", "code_snippets": ["snippet1", "snippet2"] }
  ```

- **Test**

  ```json
  { "tests_added": 3, "passed": 3, "failed": 0 }
  ```

- **Review**

  ```json
  { "approved": true, "comments": ["Looks good."] }
  ```

---

## 3. Configuration

Environment variables (with defaults):

- `OPENAI_API_KEY` **(required)** — OpenAI credential.
- `OPENAI_MODEL` (default: `gpt-4o-mini`).
- `REDPANDA_BROKERS` (default: `127.0.0.1:9092`).
- `TASK_TOPIC` (default: `agent_tasks`).
- `REPORT_TOPIC` (default: `agent_reports`).
- `DATA_DIR` (default: `./data`).

> A `config.local.json` can be used if you implemented `load_config()` to merge JSON overrides. JSON is preferred over YAML.

---

## 4. Installation

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
# Ensure these are present:
#   faust-streaming >= 0.11
#   flask >= 3.0
#   aiokafka == 0.10.0
#   pydantic >= 2.x
```

---

## 5. Starting Redpanda (deterministic in Codespaces)

```bash
docker rm -f redpanda 2>/dev/null || true
docker run -d --name=redpanda \
  -p 9092:9092 -p 9644:9644 \
  redpandadata/redpanda:v24.3.18 \
  redpanda start --overprovisioned --smp 1 --memory 1G --reserve-memory 0M \
  --node-id 0 --check=false \
  --kafka-addr PLAINTEXT://0.0.0.0:9092 \
  --advertise-kafka-addr PLAINTEXT://127.0.0.1:9092
```

> `--advertise-kafka-addr 127.0.0.1:9092` ensures clients inside the Codespaces container can reach the broker endpoint consistently (avoids `::1`/IPv6 pitfalls).

---

## 6. Running the system

Open three terminals at the repository root.

### 6.1 Worker (Faust consumer)

```bash
export REDPANDA_BROKERS=127.0.0.1:9092
export DATA_DIR=./data
make worker
# Expect the Faust banner and "Ready".
```

### 6.2 Web UI (Flask)

```bash
export DATA_DIR=./data
make web
# Open http://localhost:5000
```

### 6.3 Enqueue a task

```bash
export REDPANDA_BROKERS=127.0.0.1:9092
make send TEXT="Write a tiny Python program that prints 'Hello Earthling'"
```

You should see:

- Append-only events in `./data/reports.jsonl`.
- Artifacts in `./data/<task_id>/...json`.
- UI pages:

  - `/` — enqueue + recent reports,
  - `/reports` — table of mirrored `agent_reports`,
  - `/tasks` — list of known tasks (latest status),
  - `/task/<task_id>` — artifacts and **Replay** controls.

---

## 7. UI: Reports and Replay

- **Reports page** reads `./data/reports.jsonl` (a mirror of `agent_reports`) with newest entries first.
- **Task detail page** renders per-step artifacts and provides **Replay** buttons.
- **Replay semantics:**

  - Sends a control message with `action="replay_step"` to `agent_tasks`.
  - Worker reconstructs minimal context:

    - Reads the original prompt from the first `received` record for the task.
    - Loads prior artifacts as needed for the chosen step.

  - Reruns only the selected step, writes `step.attemptN.json`, updates `step.json`, and emits a `replayed` event.

> Replay is scoped to a single step; subsequent steps are not automatically re-executed.

---

## 8. File layout (key paths)

```
app/
  agents.py        # Agent factory functions (Architect/Implementer/Tester/Reviewer)
  bus.py           # Faust app + topics + make_report helper
  config.py        # load_config() reading ENV/JSON
  web.py           # Flask UI (Bootstrap + DictLoader templates)
  worker.py        # Faust consumer: runs 4-step pipeline, writes reports/artifacts
scripts/
  enqueue_async.py # aiokafka producer for new tasks
  replay_async.py  # aiokafka producer for step replays
data/
  reports.jsonl    # append-only mirror of agent_reports
  <task_id>/
    design@v1.json
    implement@v1.json
    test@v1.json
    review@v1.json
    ...attemptN.json (replays)
```

---

## 9. Makefile targets

```make
worker   # start Faust worker (python -m app.worker worker -l info)
web      # start Flask UI (http://localhost:5000)
send     # enqueue a task via aiokafka producer; TEXT="..." overrides prompt
replay   # (optional target) send a replay request: TASK_ID=... STEP=implement@v1 REASON="..."
```

Recommended defaults:

```make
export REDPANDA_BROKERS ?= 127.0.0.1:9092
export DATA_DIR ?= ./data
```

---

## 10. Logging and observability

- **Structured events** appended to `./data/reports.jsonl` at:

  - task receipt,
  - completion of each stage,
  - final done/error,
  - replay request and replay completion.

- **Worker logs** at INFO level identify startup configuration and step boundaries.
- **Artifacts** are human-readable JSON with normalized Pydantic output.

---

## 11. Troubleshooting

1. **`reports.jsonl` remains empty**

   - Worker not running: ensure `make worker` shows Faust “Ready”.
   - Producer used a Faust-only helper without a running app: use `scripts/enqueue_async.py` (aiokafka).
   - Broker unreachable: confirm Redpanda is listening on `127.0.0.1:9092`.

2. **Broker connectivity**

   - Use `127.0.0.1:9092` consistently (`REDPANDA_BROKERS` in each terminal).
   - Verify with:

     ```bash
     ss -ltnp | grep :9092
     docker logs redpanda --tail=50
     ```

3. **Web UI error `TemplateNotFound: base.html`**

   - Ensure `app/web.py` sets:

     ```python
     from jinja2 import DictLoader
     app.jinja_loader = DictLoader({"base.html": HTML_BASE, ...})
     ```

4. **Faust worker exits immediately**

   - Ensure `app/worker.py` ends with:

     ```python
     if __name__ == "__main__":
         app.main()
     ```

5. **Nothing shows in UI**

   - The UI reads `./data/reports.jsonl`. Confirm the same `DATA_DIR` across worker and UI.
   - Ensure file exists: `touch ./data/reports.jsonl` (worker does this on start).

6. **Replay errors**

   - Replaying `implement@test@review` requires prior artifacts. If missing, run earlier steps first or replay them in order.

---

## 12. Security and operational notes

- **Secrets:** set `OPENAI_API_KEY` via environment variables or Codespaces/Actions secrets; never commit keys.
- **Determinism:** per-step artifacts and append-only logs enable auditability and manual replay.
- **Scalability (future):** partition `agent_tasks` by `task_id`, run multiple workers in a consumer group, introduce a DB and a schema registry when needed.

---

## 13. Roadmap (suggested)

- Add SQLite/Postgres for tasks/steps/artifacts with leases and retries.
- Add Gate Engine (coverage thresholds, static analysis, secret scanning).
- GitHub PR tool: branch, commit diff, open PR, post reviewer comments.
- Vector memory/RAG for large code bases.
- UI upgrades: live stream of `agent_reports`, artifact diffs, step retries with backoff.

---

## 14. License

MIT (or your preferred license).

---

### Quick reference

```bash
# 1) Start Redpanda
docker run -d --name=redpanda -p 9092:9092 -p 9644:9644 redpandadata/redpanda:v24.3.18 \
  redpanda start --overprovisioned --smp 1 --memory 1G --reserve-memory 0M \
  --node-id 0 --check=false --kafka-addr PLAINTEXT://0.0.0.0:9092 \
  --advertise-kafka-addr PLAINTEXT://127.0.0.1:9092

# 2) Worker + UI
export REDPANDA_BROKERS=127.0.0.1:9092
export DATA_DIR=./data
make worker       # terminal A
make web          # terminal B

# 3) Enqueue and inspect
make send TEXT="Write a tiny Python program that prints 'Hello Earthling'"
tail -n 20 ./data/reports.jsonl
open http://localhost:5000
```

This system is intentionally simple and transparent to facilitate debugging and step-wise evolution to production.
