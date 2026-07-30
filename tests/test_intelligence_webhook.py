from datetime import UTC, datetime

import httpx
import pytest

from radar.intelligence.contracts import LifecycleState
from radar.intelligence.database import Database
from radar.intelligence.events import IntelligenceEvent
from radar.intelligence.repositories import SqlAlchemyIntelligenceRepository
from radar.notify.intelligence_webhook import (
    deliver_intelligence_webhook,
    retry_delay,
    sign_webhook,
)


def test_webhook_signature_is_hmac_sha256() -> None:
    body = b'{"event":"release.detected"}'

    assert sign_webhook(body, "secret") == (
        "sha256=e85adc6d6af7bb038d73d8465946be72"
        "c7be8d35865f9ed89ce234795cdb82f4"
    )


def test_webhook_retry_schedule_is_bounded() -> None:
    assert [retry_delay(attempt).total_seconds() // 60 for attempt in range(1, 7)] == [
        1,
        5,
        30,
        120,
        600,
        600,
    ]


@pytest.mark.asyncio
async def test_failed_webhook_attempt_is_signed_stored_and_scheduled(tmp_path) -> None:
    now = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    event = IntelligenceEvent.for_lifecycle(
        release_id="release:kimi-k3",
        from_state=LifecycleState.DETECTED,
        to_state=LifecycleState.VERIFIED,
        occurred_at=now,
        evidence_ids=[],
    )
    database = Database(f"sqlite:///{tmp_path / 'intelligence.db'}")
    database.create_schema()
    repository = SqlAlchemyIntelligenceRepository(database)
    repository.append_event(event)
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["signature"] = request.headers["x-radar-signature"]
        captured["event_id"] = request.headers["x-radar-event-id"]
        return httpx.Response(503, text="temporarily unavailable", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        attempt = await deliver_intelligence_webhook(
            event=event,
            destination="https://hooks.example/intelligence",
            secret="secret",
            client=client,
            repository=repository,
            now=now,
        )

    assert captured == {
        "signature": attempt.signature,
        "event_id": event.id,
    }
    assert attempt.http_status == 503
    assert attempt.response_excerpt == "temporarily unavailable"
    assert attempt.next_retry_at == now + retry_delay(1)
    assert attempt.terminal is False
    assert repository.list_webhook_attempts(event.id) == [attempt]
