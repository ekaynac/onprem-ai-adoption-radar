"""Dead-man checks for the unattended radar, run from the homelab worker.

For weeks nobody noticed CI, spec-verify and backtest going red (rescue plan
KN-7). This watches the things the owner actually consumes (the live site,
the publish pipeline, the Pulse lanes, the Telegram digest) and speaks
through Çakır, the owner's DevOps sentinel bot: once when a problem starts,
once when it clears, never on repeat.

Only public endpoints are read (Pages + the GitHub REST API), so the worker
needs no GitHub credentials.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from radar.pulse.telegram import LOCAL_TZ


STATE_PATH = Path("data") / "pulse" / "watchdog-state.json"
SITE_STALE_AFTER = timedelta(hours=6)  # publish runs every 2 h: three misses
DIGEST_DUE_HOUR = 10  # local; the digest goes out after 08:00
FAILED_RUNS_TO_ALARM = 2
RUN_LOOKBACK = timedelta(days=1)


@dataclass(frozen=True)
class Finding:
    key: str  # stable identity for dedup, e.g. "site-stale"
    message: str


def check_site(view: dict[str, Any] | None, now: datetime, error: str | None) -> list[Finding]:
    if view is None:
        return [Finding("site-unreachable", f"Live Pulse data unreachable: {error}")]
    findings = []
    generated = datetime.fromisoformat(view["generated_at"])
    age = now - generated
    if age > SITE_STALE_AFTER:
        hours = int(age.total_seconds() // 3600)
        findings.append(Finding("site-stale", f"Live site is {hours} h old (last publish {generated:%Y-%m-%d %H:%M} UTC)"))
    for section in view.get("lanes", []):
        if section.get("total", 0) == 0:
            findings.append(Finding(f"lane-empty:{section['lane']}",
                                    f"Pulse lane '{section['lane']}' is empty"))
    health = view.get("health", {})
    for source in health.get("sources", []):
        if source.get("status") != "ok":
            findings.append(Finding(f"source:{source['source']}",
                                    f"Source {source['source']} is {source['status']} "
                                    f"({source.get('count', 0)} items)"))
    if health.get("degraded"):
        findings.append(Finding("triage-degraded",
                                "Triage degraded: most shown items were ranked by rules, not Jev"))
    return findings


def check_publish(
    runs: list[dict[str, Any]] | None,
    error: str | None,
    now: datetime | None = None,
) -> list[Finding]:
    """Alarm on the two newest completed main-branch runs, both failed.

    The GitHub listing is not trusted for order: with `branch=main` it served
    2026-08-23 failures as the newest runs and raised three false alarms
    (2026-09-30..10-03). Runs are filtered to main, sorted by creation time
    here, and anything older than a day is ignored.
    """
    if runs is None:
        return [Finding("publish-unknown", f"Could not read publish runs: {error}")]
    cutoff = (now - RUN_LOOKBACK).isoformat() if now is not None else ""
    main_runs = sorted(
        (r for r in runs
         if r.get("head_branch", "main") == "main" and str(r.get("created_at", "")) >= cutoff),
        key=lambda r: str(r.get("created_at", "")),
        reverse=True,
    )
    completed = [r for r in main_runs if r.get("conclusion") not in (None, "cancelled", "skipped")]
    recent = completed[:FAILED_RUNS_TO_ALARM]
    if len(recent) == FAILED_RUNS_TO_ALARM and all(r["conclusion"] == "failure" for r in recent):
        url = recent[0].get("html_url", "")
        return [Finding("publish-failing",
                        f"Publish failed {FAILED_RUNS_TO_ALARM} times in a row: {url}")]
    return []


def check_digest(last_sent_date: str | None, now: datetime) -> list[Finding]:
    local = now.astimezone(LOCAL_TZ)
    if local.hour < DIGEST_DUE_HOUR or last_sent_date == local.date().isoformat():
        return []
    return [Finding("digest-missing",
                    f"Today's Telegram digest has not gone out (last sent: {last_sent_date or 'never'})")]


def diff_alerts(
    active: dict[str, str], findings: list[Finding],
) -> tuple[list[Finding], list[str], dict[str, str]]:
    """(newly raised, newly cleared keys, next active map)."""
    current = {f.key: f.message for f in findings}
    raised = [f for f in findings if f.key not in active]
    cleared = sorted(key for key in active if key not in current)
    return raised, cleared, current


def render_alert(
    raised: list[Finding], cleared: list[str], previous: dict[str, str],
) -> str | None:
    """Çakır's message; ``previous`` is the active map before this check."""
    if not raised and not cleared:
        return None
    lines = ["🛡️ <b>Radar watchdog</b>"]
    lines += [f"🔴 {_html(f.message)}" for f in raised]
    lines += [f"🟢 resolved: {_html(previous.get(key, key))}" for key in cleared]
    return "\n".join(lines)


def load_state(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    state = json.loads(path.read_text(encoding="utf-8"))
    active = state.get("active") if isinstance(state, dict) else None
    if not isinstance(active, dict):
        raise ValueError(f"{path}: malformed watchdog state")
    return {str(k): str(v) for k, v in active.items()}


def save_state(path: Path, active: dict[str, str], now: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"checked_at": now.isoformat(), "active": active}, indent=1),
                   encoding="utf-8")
    tmp.replace(path)


def _html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
