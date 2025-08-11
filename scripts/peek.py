# scripts/peek.py
import os, json, time
from kafka import KafkaConsumer

brokers = os.environ.get("REDPANDA_BROKERS", "127.0.0.1:9092")
topic = os.environ.get("TASK_TOPIC", "agent_tasks")

print(f"Consuming 3 messages from {topic} @ {brokers} …")
c = KafkaConsumer(
    topic,
    bootstrap_servers=[b.strip() for b in brokers.split(",") if b.strip()],
    group_id="peek-"+str(int(time.time())),
    auto_offset_reset="latest",
    value_deserializer=lambda b: json.loads(b.decode("utf-8")),
)
for i, msg in enumerate(c):
    print("msg", i+1, "key=", msg.key, "value=", msg.value)
    if i >= 2: break
