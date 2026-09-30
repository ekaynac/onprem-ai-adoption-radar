#!/usr/bin/env bash
# ct-radar worker: send the daily Pulse digest (Memati), then run the
# dead-man checks (alerts via Çakır).
#
# Runs as the unprivileged `radar` user from radar-worker.service. It never
# pulls code: per the homelab rule, an unattended pull|build|deploy loop is a
# supply-chain foothold. Code changes only through update-radar (run by the
# owner); data arrives as the published pulse.v1.json, validated on read.
set -euo pipefail

REPO_DIR="${RADAR_REPO_DIR:-/opt/radar/repo}"
SITE_URL="${RADAR_SITE_URL:-https://ekaynac.github.io/onprem-ai-adoption-radar/}"
export PATH="${HOME}/.local/bin:${PATH}"
: "${RADAR_STATE_DIR:?RADAR_STATE_DIR must be set (see radar-worker.service)}"

cd "$REPO_DIR"

# The digest must not be blocked by a watchdog problem, and vice versa;
# either failing still fails the unit so OnFailure reports it.
status=0
# --summaries: one Turkish sentence per shown item via the owner's Claude
# subscription (CLAUDE_CODE_OAUTH_TOKEN). Best effort: if claude is missing or
# fails, the digest still goes out, just without the sentences.
uv run --no-sync radar pulse telegram --root . --summaries claude-cli \
  --view-url "${SITE_URL%/}/data/pulse.v1.json" --site-url "$SITE_URL" || status=1
uv run --no-sync radar pulse watchdog --root . || status=1
exit "$status"
