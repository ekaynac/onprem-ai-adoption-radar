# ct-radar — the homelab worker

The GitHub `publish` workflow collects, triages (Jev) and publishes the site and
RSS every two hours. The homelab worker does only what GitHub cannot, because
the owner keeps these secrets at home:

| Job | Bot | Command |
|---|---|---|
| Daily Pulse digest after 08:00 Istanbul, every new item, exactly once | Memati (`@memati_claw_bot`) | `radar pulse telegram` |
| Dead-man checks every 30 min: live site age, publish failures, empty lanes, failing sources, degraded triage, missed digest | Çakır (`@cakir_claw_bot`) | `radar pulse watchdog` |
| Worker itself failed | Çakır | `notify-failure.py` via `OnFailure=` |

The worker **never pulls code on its own.** Per the homelab onboarding rule
("an unattended git pull | build | deploy loop is a supply-chain foothold"), the
checked-out code only changes when the owner runs `update-radar`, which shows
the pending commits first (the same pattern as ct-cv's `update-site`). Fresh
*data* arrives as the published `pulse.v1.json`, schema-checked on read. The
worker never pushes, so it holds no GitHub credentials. Delivery and alert
state live in `/var/lib/radar` (rootfs, covered by the nightly PBS backup).

## Files

| File | Installed as |
|---|---|
| `radar-worker.sh` | run from the clone at `/opt/radar/repo/deploy/homelab/` |
| `update-radar.sh` | `/usr/local/bin/update-radar` (root; deliberate code updates) |
| `radar-worker.service`, `radar-worker.timer`, `radar-worker-failed.service` | `/etc/systemd/system/` |
| `notify-failure.py` | run from the clone (stdlib only) |
| `env.example` | template for `/etc/radar/env` (root:radar, 0640) |

The container is created and hardened by the homelab repo's runbook
(`runbooks/radar-worker-setup.sh`, service doc `docs/services/radar.md`),
following that repo's onboarding rules: unprivileged LXC on `vmbr1`, no
inbound exposure, `unattended-upgrades` on, `onboot 1`.

## Verify

```bash
pct exec 105 -- systemctl list-timers radar-worker.timer
pct exec 105 -- journalctl -u radar-worker -n 30 --no-pager
pct exec 105 -- runuser -u radar -- env RADAR_STATE_DIR=/var/lib/radar \
  bash -c 'cd /opt/radar/repo && set -a && . /etc/radar/env && set +a && \
  ~/.local/bin/uv run radar pulse watchdog --root . --dry-run'
```
