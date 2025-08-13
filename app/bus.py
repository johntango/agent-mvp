# app/bus.py
import faust
from app.config import load_config

cfg = load_config()

app = faust.App(
    'agent-mvp',
    broker=f'kafka://{cfg["REDPANDA_BROKERS"]}',
    value_serializer='json',
    key_serializer='raw',
    web_port=cfg["WEB_PORT"],  # distinct per process via env WEB_PORT
)

task_topic    = app.topic(cfg["TASK_TOPIC"])
report_topic  = app.topic(cfg["REPORT_TOPIC"])
step_requests = app.topic(cfg["STEP_REQUESTS_TOPIC"])
step_results  = app.topic(cfg["STEP_RESULTS_TOPIC"])
dlq_topic     = app.topic(cfg["DLQ_TOPIC"])
ci_watch      = app.topic(cfg["CI_WATCH_TOPIC"])


def make_report(task_id: str, status: str, summary: str) -> dict:
    return {"task_id": task_id, "status": status, "summary": summary}
