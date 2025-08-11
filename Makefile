.PHONY: up down worker web send test
export PYTHONPATH := $(shell pwd)
export REDPANDA_BROKERS ?= 127.0.0.1:9092
export DATA_DIR ?= ./data
up:
	docker compose up -d

down:
	docker compose down -v

worker:
	python -m app.worker worker -l info

web:
	python -m app.web

TEXT ?= Implement pagination for /invoices API
send:
	python scripts/enqueue_faust.py "$(TEXT)"

test:
	pytest -q
