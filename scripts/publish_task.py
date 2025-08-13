# scripts/publish_task.py
import os, json, argparse
from pathlib import Path
from app.config import load_config
from app.git_integration import prepare_repo_and_pr
from app.state import set_meta

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", required=True)
    args = ap.parse_args()

    cfg = load_config()
    data_dir = Path(cfg["DATA_DIR"]) / args.task_id

    design = json.loads((data_dir / "design@v1.json").read_text(encoding="utf-8"))
    impl   = json.loads((data_dir / "implement@v1.json").read_text(encoding="utf-8"))
    tests  = json.loads((data_dir / "test@v1.json").read_text(encoding="utf-8"))

    pr_info = prepare_repo_and_pr(args.task_id, design, impl, tests)
    print("Opened PR:", pr_info.get("pr_url"))
    # mark as published to avoid auto re-publish
    set_meta(args.task_id, "published", "1")

if __name__ == "__main__":
    main()