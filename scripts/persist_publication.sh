#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -eq 0 ]]; then
  echo "Usage: persist_publication.sh <path> [<path> ...]" >&2
  exit 2
fi

target_branch="${RADAR_TARGET_BRANCH:-main}"
max_attempts="${RADAR_PUSH_ATTEMPTS:-3}"

git config user.name "radar-bot"
git config user.email "github-actions[bot]@users.noreply.github.com"
paths=()
for path in "$@"; do
  if [[ -e "$path" ]]; then
    paths+=("$path")
  fi
done

if [[ "${#paths[@]}" -eq 0 ]]; then
  echo "No publication history paths were produced."
  exit 0
fi

git add -f -- "${paths[@]}"

if git diff --cached --quiet; then
  echo "No publication history changes to persist."
  exit 0
fi

git commit -m "chore: radar history $(date -u +%F) [skip ci]"

attempt=1
while [[ "$attempt" -le "$max_attempts" ]]; do
  git fetch origin "$target_branch"
  git rebase "origin/$target_branch"
  if git push origin "HEAD:$target_branch"; then
    echo "Publication history persisted on attempt ${attempt}."
    exit 0
  fi
  attempt=$((attempt + 1))
done

echo "Publication history could not be pushed after ${max_attempts} attempts." >&2
exit 1
