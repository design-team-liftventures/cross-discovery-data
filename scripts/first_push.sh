#!/usr/bin/env bash
# One-time: turn this folder into the Git repo and push it to GitHub.
# Run on your Mac, from Terminal:   bash scripts/first_push.sh
set -euo pipefail
cd "$(dirname "$0")/.."
REMOTE="https://github.com/design-team-liftventures/cross-discovery-data.git"
if [ -d .git ]; then echo ".git already exists here — skip init"; else git init -b main; fi
git remote get-url origin >/dev/null 2>&1 || git remote add origin "$REMOTE"
# Safety: refuse to commit secrets or raw exports
if git status --porcelain --ignored | grep -E "_secrets|salt" | grep -v '^!!' ; then
  echo "Refusing: a secret file is not ignored"; exit 1
fi
python3 pipeline/check_pii.py
git add -A
git commit -m "Cross Discovery Data v1: pipeline, taxonomy, query skill, Jul–Aug 2026 base"
git tag -f 2026-08
git push -u origin main --tags
echo "Done. Next months: python pipeline/ingest.py && python pipeline/check_pii.py && git add -A && git commit -m 'Ingest YYYY-MM' && git tag YYYY-MM && git push --tags origin main"
