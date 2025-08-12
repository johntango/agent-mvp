import argparse, uuid, json
from kafka import KafkaProducer
from app.config import load_config

def main():
    p = argparse.ArgumentParser(description="Enqueue a task to Redpanda")
    p.add_argument("--text", required=True, help="Task description text")
    a = p.parse_args()

    cfg = load_config()
    brokers = [b.strip() for b in cfg.get("REDPANDA_BROKERS","127.0.0.1:9092").split(",") if b.strip()]
    topic = cfg.get("TASK_TOPIC", "agent_tasks")

    prod = KafkaProducer(
        bootstrap_servers=brokers,
        key_serializer=lambda k: k.encode(),
        value_serializer=lambda v: json.dumps(v).encode(),
    )
    tid = str(uuid.uuid4())
    prod.send(topic, key=tid, value={"task_id": tid, "prompt": a.text.strip()}).get(timeout=10)
    prod.flush()
    print(f"Enqueued task {tid} -> {topic} @ {brokers}")

if __name__ == "__main__":
    main()