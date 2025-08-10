.PHONY: up down worker web send test
export PYTHONPATH := $(shell pwd)

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
	python -m app.producer enqueue --text "$(TEXT)"

test:
	pytest -q
