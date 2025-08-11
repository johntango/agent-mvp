export PYTHONPATH := $(shell pwd)
export REDPANDA_BROKERS ?= 127.0.0.1:9092
export DATA_DIR ?= PYTHONPATH/data
TEXT ?= "Write a python program to say 'Hello'"

worker:
	python -m app.worker worker -l info

web:
	python -m app.web

send:
	python scripts/enqueue_faust.py --text "$(TEXT)"
