#!/bin/bash
set -e
REPO_URL="https://github.com/nchanans-ops/AI-AGENT-MINNY.git"
DIR="$(cd "$(dirname "$0")" && pwd)"
echo "📁 $DIR"
cd "$DIR"

if [ ! -d ".git" ]; then git init; fi

git add -A
git commit -m "feat: initial Thunder Support Bot — 4 modes (TEACH/QUERY/REWRITE/EXPIRY)" 2>/dev/null || echo "(no changes)"

if git remote | grep -q origin; then
  git remote set-url origin "$REPO_URL"
else
  git remote add origin "$REPO_URL"
fi

git branch -M main
git push -u origin main
echo "🚀 Push สำเร็จ! https://github.com/nchanans-ops/AI-AGENT-MINNY"
