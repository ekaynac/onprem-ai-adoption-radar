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

    if config.format == "slack":
        body: dict[str, Any] = {"text": build_slack_text(deltas, run_id)}
    else:
        body = build_payload(deltas, run_id)

    try:
        response = await client.post(config.webhook_url, json=body)
        response.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("Webhook notification failed: %s", exc)
        return False
