"""Deliver NEW stack-profile alerts to the configured webhook.

The D5 matcher already guarantees relevance (silence unless an event
touches the profile); this layer guarantees *novelty*: an append-only
delivery log ensures each alert id is pushed exactly once, so a webhook
subscriber hears about a breaking change the cycle it appears and never
again. Same contract as the ring-change notifier: off by default,
fire-and-forget, a down webhook can never fail a publish.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from radar.models import NotifyConfig
from radar.notify.webhook import text_body
from radar.storage.alert_delivery_log import load_delivered_alerts


logger = logging.getLogger(__name__)


def annotate_delivery_state(
    feed: dict[str, Any],
    root: Path,
    profile_name: str,
) -> dict[str, Any]:
    """Stamp each alert with its webhook delivery timestamp (or null).

    ``delivery_active`` is true only once at least one alert has actually
    been delivered for this profile — consumers should hide the
    delivered/pending distinction entirely until then, so profiles with
    no webhook wired never show a misleading eternal "pending".
    """
    delivered = {
        row.alert_id: row.delivered_at
        for row in load_delivered_alerts(
            root / "data" / "alerts-delivered.jsonl"
        )
        if row.profile == profile_name
    }
    for alert in feed.get("alerts", []):
        timestamp = delivered.get(alert.get("id"))
        alert["delivered_at"] = (
            timestamp.isoformat() if timestamp is not None else None
        )
    feed["delivery_active"] = bool(delivered)
    return feed


def build_alert_payload(
    alerts: list[dict[str, Any]],
    profile_name: str,
) -> dict[str, Any]:
    """Structured generic JSON payload for new stack alerts."""
    return {
        "kind": "stack-alerts",
        "profile": profile_name,
        "alert_count": len(alerts),
        "alerts": [
            {
                "verdict": alert["verdict"],
                "subject": alert["subject"],
                "what_happened": alert["what_happened"],
                "matched_components": alert["matched_components"],
                "receipts": alert["receipts"],
                "observed_at": alert["observed_at"],
            }
            for alert in alerts
        ],
    }


def build_alert_slack_text(
    alerts: list[dict[str, Any]],
    profile_name: str,
) -> str:
    """Compact Slack/Discord/Teams-compatible summary."""
    lines = [
        f"*Stack alerts* — {len(alerts)} new for profile "
        f"“{profile_name}”:"
    ]
    for alert in alerts:
        receipt = alert["receipts"][0] if alert["receipts"] else ""
        lines.append(
            f"• [{alert['verdict'].upper()}] {alert['subject']} — "
            f"{alert['what_happened']}"
            + (f" ({receipt})" if receipt.startswith("http") else "")
        )
    return "\n".join(lines)


async def send_alert_notification(
    config: NotifyConfig,
    alerts: list[dict[str, Any]],
    profile_name: str,
    client: Any,
) -> bool:
    """POST new alerts if enabled. Never raises (fire-and-forget).

    Returns True only when a request was actually sent successfully.
    """
    if not config.enabled or not config.webhook_url or not alerts:
        return False
    if config.format in {"slack", "teams"}:
        body: dict[str, Any] = text_body(
            config, build_alert_slack_text(alerts, profile_name)
        )
    else:
        body = build_alert_payload(alerts, profile_name)
    try:
        response = await client.post(config.webhook_url, json=body)
        response.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("Alert webhook delivery failed: %s", exc)
        return False
