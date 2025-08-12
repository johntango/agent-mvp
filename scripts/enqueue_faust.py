# scripts/enqueue_faust.py
import asyncio, uuid, argparse
from app.bus import app, task_topic

async def send(text: str):
    tid = str(uuid.uuid4())
    await task_topic.send(key=tid.encode(), value={"task_id": tid, "prompt": text})
    print(f"Enqueued task {tid}: {text}")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--text", dest="text_opt", help="Task text")
    p.add_argument("rest", nargs="*", help="Task text (positional)")
    args = p.parse_args()
    text = args.text_opt or " ".join(args.rest) or "hello"
    asyncio.get_event_loop().run_until_complete(send(text))

if __name__ == "__main__":
    main()