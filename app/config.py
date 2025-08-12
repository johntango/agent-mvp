import os

def load_config():
    return {
        # broker + topics
        "REDPANDA_BROKERS": os.getenv("REDPANDA_BROKERS", "127.0.0.1:9092"),
        "TASK_TOPIC": os.getenv("TASK_TOPIC", "agent_tasks"),
        "REPORT_TOPIC": os.getenv("REPORT_TOPIC", "agent_reports"),
        "STEP_REQUESTS_TOPIC": os.getenv("STEP_REQUESTS_TOPIC", "step_requests"),
        "STEP_RESULTS_TOPIC": os.getenv("STEP_RESULTS_TOPIC", "step_results"),
        "DLQ_TOPIC": os.getenv("DLQ_TOPIC", "agent_dlq"),

        # local persistence
        "DATA_DIR": os.getenv("DATA_DIR", "./data"),
        "STATE_DB": os.getenv("STATE_DB", "./data/state.sqlite"),

        # leases & retries
        "LEASE_TTL_S": int(os.getenv("LEASE_TTL_S", "1200")),
        "MAX_ATTEMPTS": int(os.getenv("MAX_ATTEMPTS", "3")),
        "BACKOFF_S": os.getenv("BACKOFF_S", "60,300,1800"),

        # faust web dashboard port (overridden per-process via env)
        "WEB_PORT": int(os.getenv("WEB_PORT", "6066")),
    }