export PYTHONPATH := $(shell pwd)
export REDPANDA_BROKERS ?= 127.0.0.1:9092
export DATA_DIR ?= ./data
TEXT ?= Implement pagination for /invoices API

worker:
	python -m app.worker worker -l info

web:
	python -m app.web

send:
	python scripts/enqueue.py --text "$(TEXT)"
