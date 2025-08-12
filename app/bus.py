# app/bus.py
import faust
from app.config import load_config

cfg = load_config()
app = faust.App(
    'agent-mvp',
    broker=f'kafka://{cfg.get("REDPANDA_BROKERS", "127.0.0.1:9092")}',
    value_serializer='json',
    key_serializer='raw',
)

task_topic = app.topic(cfg.get("TASK_TOPIC", "agent_tasks"))
report_topic = app.topic(cfg.get("REPORT_TOPIC", "agent_reports"))

def make_report(task_id: str, status: str, summary: str) -> dict:
    return {"task_id": task_id, "status": status, "summary": summary}
