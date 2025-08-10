import uuid
from app.bus import app, task_topic, make_task

@app.command()                    # ← use Faust's command wrapper
@app.option('--text', type=str)   # ← and Faust's option wrapper (not click.option)
async def enqueue(text: str):
    text = (text or "Add cursor-based pagination to the /invoices API").strip()
    tid = str(uuid.uuid4())
    await task_topic.send(key=tid.encode(), value=make_task(tid, text))
    print(f"Enqueued task {tid}: {text}")

if __name__ == "__main__":
    app.main()
