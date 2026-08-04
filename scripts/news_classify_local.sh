#!/usr/bin/env bash
# Local news-classification bot (macOS launchd).
#
# Runs the classification stage on an operator machine through the
# `claude` CLI (subscription auth — no ANTHROPIC_API_KEY), then pushes
# data/news-classified.jsonl back to main as a data-only bot commit,
# mirroring the CI persist pattern (scripts/persist_publication.sh).
# Keeps a dedicated shallow clone so it never touches a dev checkout.
#
# Install: scripts/install_news_classify_agent.sh
# Logs:    ~/Library/Logs/onprem-radar-news-classify.log
set -euo pipefail

REPO_URL="${RADAR_REPO_URL:-https://github.com/ekaynac/onprem-ai-adoption-radar.git}"
BOT_DIR="${RADAR_BOT_DIR:-$HOME/.cache/onprem-radar-news-bot}"
TARGET_BRANCH="${RADAR_TARGET_BRANCH:-main}"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

echo "[$(date -u '+%F %T')] news-classify bot run starting"

for tool in git uv claude; do
  if ! command -v "$tool" >/dev/null; then
    echo "Required tool missing from PATH: $tool" >&2
    exit 1
  fi
done

if [[ ! -d "$BOT_DIR/.git" ]]; then
  git clone --depth 50 "$REPO_URL" "$BOT_DIR"
fi
cd "$BOT_DIR"
git fetch origin "$TARGET_BRANCH"
git checkout -q "$TARGET_BRANCH"
# A discarded local commit only costs re-classifying those items next
# run (the store dedupes by news_id against origin's state).
git reset --hard "origin/$TARGET_BRANCH"

uv sync --frozen --no-dev >/dev/null

.venv/bin/radar news classify --root . --engine claude-cli

if git diff --quiet -- data/news-classified.jsonl; then
  echo "No new classifications to push."
  exit 0
fi

git config user.name "radar-news-bot"
git config user.email "radar-news-bot@users.noreply.github.com"
git add data/news-classified.jsonl
git commit -m "chore: news classification $(date -u +%F) [skip ci]"

attempt=1
while [[ "$attempt" -le 3 ]]; do
  git fetch origin "$TARGET_BRANCH"
  if ! git rebase "origin/$TARGET_BRANCH"; then
    git rebase --abort
    echo "Rebase conflict; dropping this run's commit (re-done next run)." >&2
    exit 1
  fi
  if git push origin "HEAD:$TARGET_BRANCH"; then
    echo "Classifications pushed on attempt ${attempt}."
    exit 0
  fi
  attempt=$((attempt + 1))
done

echo "Could not push classifications after 3 attempts." >&2
exit 1
