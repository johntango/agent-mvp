from __future__ import annotations
import argparse

from app.agents.test_generator import generate_tests_from_story
from scripts.pipeline_promote import promote_to_repo, commit_push_open_pr


def main() -> None:
    ap = argparse.ArgumentParser(prog="agent-mvp")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gen-tests", help="Generate pytest files from story.json")
    g.add_argument("task_id")
    g.add_argument("--model", default=None)

    p = sub.add_parser("promote", help="Promote staged files into repo and open PR")
    p.add_argument("task_id")

    args = ap.parse_args()

    if args.cmd == "gen-tests":
        written = generate_tests_from_story(args.task_id, model=args.model or "gpt-4o-mini")
        print("\n".join(str(p) for p in written))
    elif args.cmd == "promote":
        files = promote_to_repo(args.task_id)
        print(f"Promoted {len(files)} files.")
        commit_push_open_pr(args.task_id)


if __name__ == "__main__":
    main()