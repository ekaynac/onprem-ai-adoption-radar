"""Signed webhook payload helpers and bounded retry policy."""

import hashlib
import hmac
import json
from datetime import datetime, timedelta
from typing import Protocol

import httpx

from radar.intelligence.events import IntelligenceEvent, WebhookAttempt


_RETRY_MINUTES = (1, 5, 30, 120, 600)


def sign_webhook(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def retry_delay(attempt: int) -> timedelta:
    index = min(max(attempt, 1), len(_RETRY_MINUTES)) - 1
    return timedelta(minutes=_RETRY_MINUTES[index])


class WebhookRepository(Protocol):
    def record_webhook_attempt(self, attempt: WebhookAttempt) -> bool: ...


async def deliver_intelligence_webhook(
    *,
    event: IntelligenceEvent,
    destination: str,
    secret: str,
    client: httpx.AsyncClient,
    repository: WebhookRepository,
    now: datetime,
    attempt_number: int = 1,
) -> WebhookAttempt:
    """Deliver one canonical event and durably record the result."""

    body = json.dumps(
        event.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    signature = sign_webhook(body, secret)
    status: int | None = None
    excerpt = ""
    try:
        response = await client.post(
            destination,
            content=body,
            headers={
                "content-type": "application/json",
                "x-radar-event-id": event.id,
                "x-radar-signature": signature,
                "x-radar-schema-version": event.schema_version,
            },
        )
        status = response.status_code
        excerpt = response.text[:500]
    except httpx.HTTPError as exc:
        excerpt = str(exc)[:500]

    succeeded = status is not None and 200 <= status < 300
    exhausted = attempt_number > len(_RETRY_MINUTES)
    terminal = succeeded or exhausted
    next_retry_at = (
        None if terminal else now + retry_delay(attempt_number)
    )
    identity = "|".join((event.id, destination, str(attempt_number)))
    attempt = WebhookAttempt(
        id=f"webhook-attempt:{hashlib.sha256(identity.encode()).hexdigest()}",
        event_id=event.id,
        destination=destination,
        attempt=attempt_number,
        signature=signature,
        http_status=status,
        response_excerpt=excerpt,
        next_retry_at=next_retry_at,
        terminal=terminal,
        attempted_at=now,
    )
    repository.record_webhook_attempt(attempt)
    return attempt
