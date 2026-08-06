"""Post-scan webhook notifier.

Fires only when a scan produced ring changes (promotions/demotions/new), so
subscribers hear about decisions, not every scan. Fire-and-forget: any failure
is logged and swallowed — a scan must never fail because a webhook is down.
"""

from __future__ import annotations

import logging
from typing import Any

from radar.models import NotifyConfig
from radar.pipeline.delta import CardDelta, ChangeType
from radar.reports.digest import WeeklyDigest


logger = logging.getLogger(__name__)

# Ring moves worth notifying about (not silent UPDATED-only churn).
_NOTIFY_CHANGES = {ChangeType.PROMOTED, ChangeType.DEMOTED, ChangeType.NEW}


def _ring_changes(deltas: list[CardDelta]) -> list[CardDelta]:
    return [d for d in deltas if d.change_type in _NOTIFY_CHANGES]


def build_payload(deltas: list[CardDelta], run_id: str) -> dict[str, Any]:
    """Structured generic JSON payload of this scan's ring changes."""
    changes = [
        {
            "project": d.project,
            "category": d.category.value,
            "change": d.change_type.value,
            "from": d.previous_ring.value if d.previous_ring else None,
            "to": d.current_ring.value,
        }
        for d in _ring_changes(deltas)
    ]
    return {"run_id": run_id, "change_count": len(changes), "changes": changes}


def teams_message(
    text: str,
    actions: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """The Adaptive Card envelope Teams Workflows webhooks require.

    Modern Teams webhooks (Power Automate "when a webhook request is
    received") only render ``attachments`` carrying an Adaptive Card —
    plain ``{"text": ...}`` posts are dropped silently. The TextBlock
    renders a markdown subset (bold, ``[title](url)`` links, ``- ``
    lists); bare URLs are NOT clickable, so callers should pass
    markdown links and/or ``actions`` ((title, url) pairs rendered as
    Action.OpenUrl buttons).
    """
    content: dict[str, Any] = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [{"type": "TextBlock", "text": text, "wrap": True}],
    }
    if actions:
        content["actions"] = [
            {"type": "Action.OpenUrl", "title": title, "url": url}
            for title, url in actions
        ]
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": content,
            }
        ],
    }


def text_body(config: NotifyConfig, text: str) -> dict[str, Any]:
    """The text payload matching the configured webhook dialect."""
    if config.format == "teams":
        return teams_message(text)
    return {"text": text}


def build_slack_text(deltas: list[CardDelta], run_id: str) -> str:
    """A compact Slack/Discord/Teams-compatible summary string."""
    lines = [f"*Adoption radar* — {len(_ring_changes(deltas))} ring change(s) in {run_id}:"]
    for d in _ring_changes(deltas):
        if d.change_type == ChangeType.NEW:
            lines.append(f"• {d.project}: new → {d.current_ring.value}")
        else:
            frm = d.previous_ring.value if d.previous_ring else "?"
            lines.append(
                f"• {d.project}: {frm} → {d.current_ring.value} ({d.change_type.value})"
            )
    return "\n".join(lines)


async def send_notification(
    config: NotifyConfig,
    deltas: list[CardDelta],
    run_id: str,
    client: Any,
) -> bool:
    """POST a notification if enabled and there are ring changes. Never raises.

    Returns True only when a request was actually sent successfully.
    """
    if not config.enabled or not config.webhook_url:
        return False
    if not _ring_changes(deltas):
        return False

    if config.format in {"slack", "teams"}:
        body: dict[str, Any] = text_body(
            config, build_slack_text(deltas, run_id)
        )
    else:
        body = build_payload(deltas, run_id)

    try:
        response = await client.post(config.webhook_url, json=body)
        response.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("Webhook notification failed: %s", exc)
        return False


def build_digest_payload(digest: WeeklyDigest) -> dict[str, Any]:
    """Structured generic JSON payload for a weekly digest."""
    return {
        "label": digest.label,
        "summary": digest.summary_line,
        "onprem_candidates": [e.repo for e in digest.trending_onprem],
        "auto_added": [a.repo for a in digest.auto_added],
        "ring_changes": len(digest.changes),
    }


async def send_digest_notification(
    config: NotifyConfig,
    digest: WeeklyDigest,
    client: Any,
    page_url: str | None = None,
) -> bool:
    """POST the digest summary if enabled. Never raises (fire-and-forget)."""
    if not config.enabled or not config.webhook_url:
        return False
    if config.format == "teams":
        body: dict[str, Any] = teams_message(
            digest.summary_line,
            actions=[("Open digest", page_url)] if page_url else None,
        )
    elif config.format == "slack":
        body = {
            "text": digest.summary_line
            + (f" {page_url}" if page_url else "")
        }
    else:
        body = build_digest_payload(digest)
        if page_url:
            body["url"] = page_url
    try:
        response = await client.post(config.webhook_url, json=body)
        response.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("Digest webhook failed: %s", exc)
        return False
