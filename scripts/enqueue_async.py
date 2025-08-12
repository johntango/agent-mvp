# scripts/enqueue_async.py  (ensure this exact producer is used by Makefile/UI)
import argparse, asyncio, json, uuid, os
from aiokafka import AIOKafkaProducer

def env(name, default):
    return os.environ.get(name, default)

async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--text", required=True, help="Task description")
    args = p.parse_args()

    brokers = env("REDPANDA_BROKERS", "127.0.0.1:9092")
    topic   = env("TASK_TOPIC", "agent_tasks")
    tid     = str(uuid.uuid4())
    payload = {"task_id": tid, "prompt": args.text.strip()}

    print(f"[enqueue] brokers={brokers} topic={topic} task_id={tid}")

    producer = AIOKafkaProducer(
        bootstrap_servers=[b.strip() for b in brokers.split(",") if b.strip()],
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8"),
    )
    await producer.start()
    try:
        await producer.send_and_wait(topic, key=tid, value=payload)
        print(f"[enqueue] sent: {payload}")
    finally:
        await producer.stop()

if __name__ == "__main__":
    asyncio.run(main())
