#!/usr/bin/env bash
# Deliberate code update for ct-radar (mirrors ct-cv's update-site): show what
# would change, then fast-forward and re-sync. Never run from a timer.
#
#   pct exec 105 -- /usr/local/bin/update-radar          # show pending commits, ask
#   pct exec 105 -- /usr/local/bin/update-radar --yes    # apply without asking
# (full path: pct exec does not put /usr/local/bin on PATH)
set -euo pipefail

REPO_DIR="${RADAR_REPO_DIR:-/opt/radar/repo}"
as_radar() { runuser -u radar -- env HOME=/opt/radar PATH="/opt/radar/.local/bin:/usr/bin:/bin" "$@"; }

as_radar git -C "$REPO_DIR" fetch --quiet origin main
pending="$(as_radar git -C "$REPO_DIR" log --oneline HEAD..origin/main)"
if [ -z "$pending" ]; then
  echo "ct-radar is already at origin/main ($(as_radar git -C "$REPO_DIR" rev-parse --short HEAD))."
  exit 0
fi
echo "Pending commits:"
echo "$pending"
echo
echo "Worker-relevant changes:"
as_radar git -C "$REPO_DIR" diff --stat HEAD origin/main -- src/radar/pulse src/radar/cli/pulse_cli.py deploy/homelab pyproject.toml uv.lock
if [ "${1:-}" != "--yes" ]; then
  read -r -p "Apply? [y/N] " answer
  [ "$answer" = "y" ] || { echo "Nothing changed."; exit 0; }
fi
as_radar git -C "$REPO_DIR" merge --quiet --ff-only origin/main
as_radar bash -c "cd '$REPO_DIR' && uv sync --quiet --locked --no-dev"
install -m 0644 "$REPO_DIR"/deploy/homelab/radar-worker{.service,.timer,-failed.service} /etc/systemd/system/
systemctl daemon-reload
echo "ct-radar now at $(as_radar git -C "$REPO_DIR" rev-parse --short HEAD)."
