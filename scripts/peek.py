import os, json, time, asyncio
from aiokafka import AIOKafkaConsumer
async def peek(topic):
    c=AIOKafkaConsumer(topic,
        bootstrap_servers=os.environ.get("REDPANDA_BROKERS","127.0.0.1:9092"),
        group_id=f"peek-{topic}-{int(time.time())}",
        auto_offset_reset="latest",
        value_deserializer=lambda b: json.loads(b.decode()))
    await c.start()
    try:
        print("Waiting for 1 message on", topic, "…")
        m=await c.getone()
        print("GOT:", m.value)
    finally:
        await c.stop()