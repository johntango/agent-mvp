import faust
from app.config import load_config

cfg = load_config()
app = faust.App(
    'agent-mvp',
    broker=f'kafka://{cfg["REDPANDA_BROKERS"]}',
    value_serializer='json',
    key_serializer='raw',
)

task_topic = app.topic(cfg["TASK_TOPIC"])
report_topic = app.topic(cfg["REPORT_TOPIC"])

def make_task(task_id: str, prompt: str) -> dict:
    return {"task_id": task_id, "prompt": prompt}

def make_report(task_id: str, status: str, summary: str) -> dict:
    return {"task_id": task_id, "status": status, "summary": summary}
