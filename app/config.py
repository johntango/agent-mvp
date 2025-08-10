import os
def load_config():
    return {
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
        "MODEL": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "REDPANDA_BROKERS": os.environ.get("REDPANDA_BROKERS", "localhost:9092"),
        "TASK_TOPIC": os.environ.get("TASK_TOPIC", "agent_tasks"),
        "REPORT_TOPIC": os.environ.get("REPORT_TOPIC", "agent_reports"),
        "DATA_DIR": os.environ.get("DATA_DIR", "./data"),
    }
