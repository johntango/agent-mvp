# JSON persistence (debug)
This build writes per-step artifacts and a global state file:
- `./data/<task_id>/design@v1.json`, `implement@v1.json`, `test@v1.json`, `review@v1.json`
- `./data/state.json` (tasks, steps, artifacts)

Tail summaries:
```
tail -n 20 ./data/reports.jsonl
```
Inspect state:
```
cat ./data/state.json | jq .
```

# Agent MVP (OpenAI Agents SDK + Faust/Redpanda + Flask UI)

Minimal multi-agent MVP with JSON message serialization, Codespaces support, and a Bootstrap UI.

## Quickstart

1. API key:
   ```bash
   export OPENAI_API_KEY=sk-...
   ```

2. Start Redpanda:
   ```bash
   docker run -d --name=redpanda -p 9092:9092 -p 9644:9644 redpandadata/redpanda:v24.3.18 \     redpanda start --overprovisioned --smp 1 --memory 1G --reserve-memory 0M --node-id 0 --check=false \     --kafka-addr PLAINTEXT://0.0.0.0:9092 --advertise-kafka-addr PLAINTEXT://localhost:9092
   ```

3. Worker:
   ```bash
   make worker
   ```

4. UI:
   ```bash
   make web   # http://localhost:5000
   ```

5. Enqueue a task:
   ```bash
   make send
   # or: Implement cursor pagimake send TEXT="nation for /invoices API"
   ```
# Agent MVP — Autonomous Multi-Agent Software Worker

*(OpenAI Agents SDK + Faust/Redpanda + Flask + GitHub Actions; Codespaces-ready)*

## Overview

This repository is a minimal, end-to-end system that accepts natural-language software tasks, decomposes and executes them with a chain of agents, and publishes a reviewable report—without interrupting running workers.

**Key components**

* **Agents (factory functions, no classes):** Architect → Implementer → Tester → Reviewer, orchestrated by a Triage agent (OpenAI Agents SDK).
* **Messaging:** Faust streaming over **Redpanda** (Kafka API).
  – Consumer/worker is Faust.
  – Producer is a small **kafka-python** script to avoid CLI collisions.
* **UI:** Flask + **Bootstrap** dashboard (enqueue tasks, view reports) with read-only logs.
* **Persistence & logs:** JSONL report log at `./data/reports.jsonl`.
* **CI:** GitHub Actions running pytest on push/PR.
* **Dev:** Ready for **GitHub Codespaces** (Docker-in-Docker feature; ports forwarded).

---

## Repository layout

```
agent-mvp/
├─ app/
│  ├─ __init__.py
│  ├─ agents.py          # agent factory functions + triage handoff
│  ├─ bus.py             # Faust app + topic handles + message helpers
│  ├─ config.py          # env/config loader
│  ├─ web.py             # Flask + Bootstrap dashboard
│  └─ worker.py          # Faust worker: consumes tasks, runs agents, emits reports
├─ scripts/
│  ├─ enqueue.py         # kafka-python producer to enqueue tasks
│  └─ push_to_github.sh  # helper to initialize and push the repo
├─ tests/
│  └─ test_smoke.py
├─ .github/workflows/ci.yml
├─ .devcontainer/devcontainer.json
├─ docker-compose.yml    # optional Redpanda/Console
├─ requirements.txt
├─ Makefile
├─ config.local.json     # optional JSON overrides
└─ README.md
```

---

## Data flow (concise)

```
[User / UI / CLI enqueue] --(Kafka JSON)->  [agent_tasks topic]
      ↓                                            ↓
   Flask UI or scripts/enqueue.py            Faust worker (app/worker.py)
                                               └─ Triage → Architect → Implementer → Tester → Reviewer
                                                                ↓
                                                       Report JSON (summary text)
                                                                ↓
                              [agent_reports topic] & append-only JSONL at ./data/reports.jsonl
                                                                ↓
                                                  UI lists latest reports without blocking worker
```

**Topics (default):**

* `agent_tasks` (input)
* `agent_reports` (output)

---

## Prerequisites

* **Python** 3.11+
* **Docker** (for Redpanda or Codespaces)
* **OpenAI API key**: set `OPENAI_API_KEY`
* Optional: **Redpanda Console** (if using `docker-compose.yml`)

---

## Configuration

Environment variables (defaults shown):

* `OPENAI_API_KEY` – **required**
* `OPENAI_MODEL` (default: `gpt-4o-mini`)
* `REDPANDA_BROKERS` (default: `localhost:9092`)
* `TASK_TOPIC` (default: `agent_tasks`)
* `REPORT_TOPIC` (default: `agent_reports`)
* `DATA_DIR` (default: `./data`)

You may also place overrides in **`config.local.json`** (JSON is preferred over YAML in this project):

```json
{
  "OPENAI_MODEL": "gpt-4o-mini",
  "REDPANDA_BROKERS": "localhost:9092",
  "TASK_TOPIC": "agent_tasks",
  "REPORT_TOPIC": "agent_reports",
  "DATA_DIR": "./data"
}
```

---

## Quickstart

### 1) Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 2) Start Redpanda (choose one)

**A. Your existing command (preferred):**

```bash
docker run -d --name=redpanda -p 9092:9092 -p 9644:9644 redpandadata/redpanda:v24.3.18 \
  redpanda start --overprovisioned --smp 1 --memory 1G --reserve-memory 0M --node-id 0 --check=false \
  --kafka-addr PLAINTEXT://0.0.0.0:9092 --advertise-kafka-addr PLAINTEXT://localhost:9092
```

**B. Or: docker-compose**

```bash
docker compose up -d
# Console at http://localhost:8080 (if using compose)
```

### 3) Run the worker

From the **repo root**:

```bash
export OPENAI_API_KEY=sk-...   # required
make worker
```

### 4) Start the UI

```bash
make web
# UI: http://localhost:5000
```

### 5) Enqueue a task

```bash
# default task text
make send

# or custom text
make send TEXT="Implement pagination for /invoices API"
```

The task is published to `agent_tasks`. The worker processes it and writes a summary to `agent_reports` and to `./data/reports.jsonl`. The UI lists recent reports.

---

## Message schemas (JSON)

**Task**

```json
{
  "task_id": "uuid-4",
  "prompt": "Implement pagination for /invoices API"
}
```

**Report**

```json
{
  "task_id": "uuid-4",
  "status": "done",
  "summary": "High-level outcome text from the triage/agent chain."
}
```

---

## Agents and execution model

* **Factory functions** (no classes):
  `make_architect_agent()`, `make_implementer_agent()`, `make_tester_agent()`, `make_reviewer_agent()`, and `make_triage_agent()` (handoffs array).

* **Triage agent**: Receives the prompt and routes work **Architect → Implementer → Tester → Reviewer** via the OpenAI Agents SDK handoff mechanism.
  Output is a compact, human-readable **summary**. (This MVP omits intermediate artifacts; see “Extensibility”.)

* **Worker** (`app/worker.py`):
  Faust agent that:

  1. Consumes a JSON task from `agent_tasks`.
  2. Runs the triage pipeline (`Runner.run(...)`).
  3. Emits a JSON report to `agent_reports`.
  4. Appends to `./data/reports.jsonl` for non-blocking UI display.

---

## UI

* **Framework:** Flask + **Bootstrap**.
* **Function:** One input field to enqueue a task; table view of the latest reports.
* **Non-intrusive:** UI reads `./data/reports.jsonl`; it never blocks the worker.

---

## CI (GitHub Actions)

Workflow: `.github/workflows/ci.yml`

* Triggers on push and PR.
* Installs dependencies and runs `pytest -q`.

---

## Codespaces usage

* This repo includes `.devcontainer/devcontainer.json` with Docker-in-Docker enabled.
* On first open Codespaces runs `postCreateCommand: pip install -r requirements.txt`.
* Forwarded ports: **5000** (UI), **9092** (Kafka), **8080** (Console if using compose).

**If imports fail in Codespaces**

```bash
python -V
which python
python -m pip -V
python -m pip install -r requirements.txt
python - <<'PY'
import sys; print(sys.executable)
import faust, kafka
print("faust OK", faust.__version__)
print("kafka-python OK", kafka.__version__)
PY
```

---

## Makefile targets

```make
make worker   # start Faust worker (consumer)
make web      # start Flask UI
make send     # enqueue default task via scripts/enqueue.py
make send TEXT="your task here"  # enqueue custom text
make up       # optional: docker compose up Redpanda
make down     # optional: docker compose down -v
make test     # pytest -q
```

> The Makefile exports `PYTHONPATH := $(pwd)` so `python -m app.*` resolves from the repo root reliably.

---

## Security and operational notes

* **Secrets:** `OPENAI_API_KEY` is consumed at runtime only and not stored. Do not commit keys. Use Codespaces/Actions secrets where possible.
* **Network:** Worker egress is to OpenAI API and to Redpanda. The UI is local by default.
* **Supply chain:** Dependencies are pinned at minimum versions; adjust and lock as appropriate for your environment.

---

## Extensibility roadmap

* **Artifacts:** Persist intermediate artifacts (design, diffs, test reports) to object storage and link from the UI.
* **Gate policies:** Add static analysis, coverage thresholds, and promotion gates.
* **Peer review:** Add a Reviewer agent that renders a structured checklist and blocks promotion until “green”.
* **Schema registry:** Use Avro/JSON-Schema + registry for message evolution.
* **Auth:** Add authentication to the UI and productionize deployment.

---

## Troubleshooting

| Symptom                          | Likely cause                       | Resolution                                                                                     |
| -------------------------------- | ---------------------------------- | ---------------------------------------------------------------------------------------------- |
| `NoBrokersAvailable`             | Redpanda not reachable, wrong port | Ensure broker on `localhost:9092` (or update `REDPANDA_BROKERS`).                              |
| Nothing appears in UI            | Worker not running or no logs yet  | `make worker` in one terminal; then enqueue; check `./data/reports.jsonl`.                     |
| Import errors (`faust`, `kafka`) | Different Python env/interpreter   | Always use `python -m pip install -r requirements.txt` and run `python` from same interpreter. |
| Kafka value/key errors           | Null key/value                     | The producer always sends both; if customizing, ensure both key and JSON value are provided.   |

---

## License

MIT

---

## Acknowledgements

This MVP uses **Faust Streaming** for Python stream processing, **Redpanda** as the Kafka-compatible broker, **kafka-python** for producer simplicity, and **OpenAI Agents SDK** for multi-agent orchestration.
