export PYTHONPATH := $(shell pwd)
export REDPANDA_BROKERS ?= 127.0.0.1:9092
export DATA_DIR ?= ./data
TEXT ?= "Write a python program to say 'Hello'"

worker:
	python -m app.worker worker -l info

web:
	python -m app.web


TEXT ?= Implement pagination for /invoices API

send:
	python scripts/enqueue_async.py --text "$(TEXT)"
