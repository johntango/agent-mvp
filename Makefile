PYTHON ?= python
export PYTHONPATH := $(shell pwd)
export REDPANDA_BROKERS ?= 127.0.0.1:9092
export DATA_DIR ?= ./data
TEXT ?= Implement pagination for /invoices API

# Faust services — each on its own web port
planner:
	WEB_PORT=6066 $(PYTHON) -m app.planner_service worker -l info

worker:
	WEB_PORT=6067 $(PYTHON) -m app.worker worker -l info

orchestrator:
	WEB_PORT=6068 $(PYTHON) -m app.orchestrator_service worker -l info

# Flask UI
web:
	$(PYTHON) -m app.web

# Enqueue a new task (aiokafka producer)
send:
	$(PYTHON) scripts/enqueue_async.py --text "$(TEXT)"