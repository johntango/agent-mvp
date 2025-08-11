import asyncio, uuid, sys
from app.bus import app, task_topic

async def main(text: str):
    tid = str(uuid.uuid4())
    await task_topic.send(key=tid.encode(), value={"task_id": tid, "prompt": text})
    print(f"Enqueued task {tid}: {text}")

if __name__ == "__main__":
    text = " ".join(sys.argv[1:]).strip() or "hello"
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main(text))