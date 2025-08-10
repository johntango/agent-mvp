#!/usr/bin/env bash
set -euo pipefail
REPO_SLUG="${1:-johntango/agent-mvp}"
DEFAULT_BRANCH="${2:-main}"
git init -b "$DEFAULT_BRANCH"
git add .
git commit -m "Initial commit: Agent MVP"
git remote add origin "https://github.com/${REPO_SLUG}.git"
echo "Now push with: git push -u origin $DEFAULT_BRANCH"
