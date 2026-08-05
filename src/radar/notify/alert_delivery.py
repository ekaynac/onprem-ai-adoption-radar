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
from radar.notify.webhook import teams_message, text_body
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


def alert_link(alert: dict[str, Any], base_url: str | None) -> str | None:
    """The radar page that explains this alert, when one exists.

    Ring moves point at the model's catalog page; news alerts already
    carry the source article in ``receipts``. The static site routes
    with a HashRouter, hence the ``/#/`` prefix.
    """
    if not base_url:
        return None
    if alert.get("event_type") == "ring-move":
        return f"{base_url.rstrip('/')}/#/catalog/{alert['subject']}"
    return None


def build_alert_payload(
    alerts: list[dict[str, Any]],
    profile_name: str,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Structured generic JSON payload for new stack alerts."""
    payload: dict[str, Any] = {
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
                "link": alert_link(alert, base_url),
            }
            for alert in alerts
        ],
    }
    if base_url:
        payload["site"] = f"{base_url.rstrip('/')}/#/workspaces"
    return payload


def build_alert_slack_text(
    alerts: list[dict[str, Any]],
    profile_name: str,
    base_url: str | None = None,
) -> str:
    """Compact Slack/Discord/Teams-compatible summary."""
    lines = [
        f"*Stack alerts* — {len(alerts)} new for profile "
        f"“{profile_name}”:"
    ]
    for alert in alerts:
        receipt = alert["receipts"][0] if alert["receipts"] else ""
        link = receipt if receipt.startswith("http") else alert_link(
            alert, base_url
        )
        lines.append(
            f"• [{alert['verdict'].upper()}] {alert['subject']} — "
            f"{alert['what_happened']}"
            + (f" ({link})" if link else "")
        )
    if base_url:
        lines.append(
            f"Full feed with delivery badges: "
            f"{base_url.rstrip('/')}/#/workspaces"
        )
    return "\n".join(lines)


def build_alert_teams_message(
    alerts: list[dict[str, Any]],
    profile_name: str,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Adaptive Card with clickable per-alert links and a feed button.

    Bare URLs are not clickable inside Teams card TextBlocks, so links
    ride as markdown ``[details ↗](url)`` and the feed as an
    Action.OpenUrl button.
    """
    lines = [
        f"**Stack alerts** — {len(alerts)} new for profile "
        f"“{profile_name}”:"
    ]
    for alert in alerts:
        receipt = alert["receipts"][0] if alert["receipts"] else ""
        link = receipt if receipt.startswith("http") else alert_link(
            alert, base_url
        )
        lines.append(
            f"- **[{alert['verdict'].upper()}]** {alert['subject']} — "
            f"{alert['what_happened']}"
            + (f" [details ↗]({link})" if link else "")
        )
    actions = (
        [("Open radar feed", f"{base_url.rstrip('/')}/#/workspaces")]
        if base_url
        else None
    )
    return teams_message("\n\n".join(lines), actions=actions)


async def send_alert_notification(
    config: NotifyConfig,
    alerts: list[dict[str, Any]],
    profile_name: str,
    client: Any,
    base_url: str | None = None,
) -> bool:
    """POST new alerts if enabled. Never raises (fire-and-forget).

    Returns True only when a request was actually sent successfully.
    """
    if not config.enabled or not config.webhook_url or not alerts:
        return False
    if config.format == "teams":
        body: dict[str, Any] = build_alert_teams_message(
            alerts, profile_name, base_url
        )
    elif config.format == "slack":
        body = text_body(
            config, build_alert_slack_text(alerts, profile_name, base_url)
        )
    else:
        body = build_alert_payload(alerts, profile_name, base_url)
    try:
        response = await client.post(config.webhook_url, json=body)
        response.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("Alert webhook delivery failed: %s", exc)
        return False
