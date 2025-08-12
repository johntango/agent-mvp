# scripts/replay_async.py
import argparse, asyncio, json, os, uuid
from aiokafka import AIOKafkaProducer

def env(name, default):
    return os.environ.get(name, default)

async def main():
    p = argparse.ArgumentParser(description="Replay a single agent step for an existing task")
    p.add_argument("--task-id", required=True, help="Existing task UUID")
    p.add_argument("--step", required=True, choices=["design@v1","implement@v1","test@v1","review@v1"],
                   help="Step to replay")
    p.add_argument("--reason", default="", help="Optional reason note")
    args = p.parse_args()

    brokers = env("REDPANDA_BROKERS", "127.0.0.1:9092")
    topic   = env("TASK_TOPIC", "agent_tasks")

    payload = {
        "action": "replay_step",
        "task_id": args.task_id,
        "step_id": args.step,
        "reason": args.reason,
        # no prompt here; worker will reconstruct from reports.jsonl
    }

    print(f"[replay] brokers={brokers} topic={topic} payload={payload}")

    producer = AIOKafkaProducer(
        bootstrap_servers=[b.strip() for b in brokers.split(",") if b.strip()],
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8"),
    )
    await producer.start()
    try:
        # key = task_id to keep ordering-by-task
        await producer.send_and_wait(topic, key=payload["task_id"], value=payload)
        print("[replay] sent.")
    finally:
        await producer.stop()

if __name__ == "__main__":
    asyncio.run(main())
