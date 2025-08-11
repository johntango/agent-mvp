import argparse, uuid, json
from kafka import KafkaProducer
from app.config import load_config

def main():
    parser = argparse.ArgumentParser(description="Enqueue a task to Redpanda")
    parser.add_argument("--text", required=True, help="Task description text")
    args = parser.parse_args()

    cfg = load_config()
    brokers = [b.strip() for b in cfg["REDPANDA_BROKERS"].split(",") if b.strip()]
    topic = cfg["TASK_TOPIC"]

    producer = KafkaProducer(
        bootstrap_servers=brokers,
        key_serializer=lambda k: k.encode(),
        value_serializer=lambda v: json.dumps(v).encode(),
    )

    tid = str(uuid.uuid4())
    msg = {"task_id": tid, "prompt": args.text.strip()}
    producer.send(topic, key=tid, value=msg).get(timeout=10)
    producer.flush()
    print(f"Enqueued task {tid}: {args.text} -> topic={topic} brokers={brokers}")

if __name__ == "__main__":
    main()