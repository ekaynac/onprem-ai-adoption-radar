#!/usr/bin/env bash
# Deliberate code update for ct-radar (mirrors ct-cv's update-site): show what
# would change, then fast-forward and re-sync. Never run from a timer.
#
#   pct exec 105 -- /usr/local/bin/update-radar          # show pending commits, ask
#   pct exec 105 -- /usr/local/bin/update-radar --yes    # apply without asking
# (full path: pct exec does not put /usr/local/bin on PATH)
#
# Root installs systemd units ONLY from its own clone of the public origin
# (DEPLOY_DIR), never from REPO_DIR: REPO_DIR belongs to the `radar` user, so a
# compromised worker could edit unit files there and become root at the next
# update (homelab security audit 2026-11-05). The mirror is checked out at the
# exact commit the worker was fast-forwarded to; a commit that is not in origin
# fails the update.
set -euo pipefail

REPO_DIR="${RADAR_REPO_DIR:-/opt/radar/repo}"
DEPLOY_DIR="${RADAR_DEPLOY_DIR:-/usr/local/share/radar-deploy}"
as_radar() { runuser -u radar -- env HOME=/opt/radar PATH="/opt/radar/.local/bin:/usr/bin:/bin" "$@"; }

[ -d "$DEPLOY_DIR/.git" ] || { echo "missing $DEPLOY_DIR: run homelab runbooks/radar-worker-setup.sh first" >&2; exit 1; }

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
as_radar git -C "$REPO_DIR" diff --stat HEAD origin/main -- src/radar config deploy/homelab pyproject.toml uv.lock
if [ "${1:-}" != "--yes" ]; then
  read -r -p "Apply? [y/N] " answer
  [ "$answer" = "y" ] || { echo "Nothing changed."; exit 0; }
fi
as_radar git -C "$REPO_DIR" merge --quiet --ff-only origin/main
as_radar bash -c "cd '$REPO_DIR' && uv sync --quiet --locked --no-dev"

sha="$(as_radar git -C "$REPO_DIR" rev-parse HEAD)"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "bad worker HEAD: $sha" >&2; exit 1; }
git -C "$DEPLOY_DIR" fetch --quiet origin
git -C "$DEPLOY_DIR" -c advice.detachedHead=false checkout --quiet --detach "$sha"
install -m 0644 "$DEPLOY_DIR"/deploy/homelab/radar-worker{.service,.timer,-failed.service} /etc/systemd/system/
install -m 0755 "$DEPLOY_DIR"/deploy/homelab/update-radar.sh /usr/local/bin/update-radar
systemctl daemon-reload
echo "ct-radar now at ${sha:0:7}."
