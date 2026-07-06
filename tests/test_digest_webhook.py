"""Fire-and-forget digest webhook."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from radar.models import NotifyConfig
from radar.notify.webhook import build_digest_payload, send_digest_notification
from radar.reports.digest import WeeklyDigest


def _digest():
    return WeeklyDigest(label="2026-W28", week_start=datetime(2026, 7, 6, tzinfo=UTC),
                        week_end=datetime(2026, 7, 13, tzinfo=UTC),
                        generated_at=datetime(2026, 7, 8, tzinfo=UTC))


def test_payload_has_label_and_summary():
    payload = build_digest_payload(_digest())
    assert payload["label"] == "2026-W28" and "summary" in payload


class _OKClient:
    def __init__(self): self.posted = None
    async def post(self, url, json):
        self.posted = (url, json)
        class _R:
            def raise_for_status(self): return None
        return _R()


class _BoomClient:
    async def post(self, url, json): raise RuntimeError("down")


@pytest.mark.asyncio
async def test_sends_when_enabled():
    client = _OKClient()
    ok = await send_digest_notification(
        NotifyConfig(enabled=True, webhook_url="https://x/hook"), _digest(), client)
    assert ok is True and client.posted[0] == "https://x/hook"


@pytest.mark.asyncio
async def test_disabled_is_noop():
    ok = await send_digest_notification(NotifyConfig(enabled=False), _digest(), _OKClient())
    assert ok is False


@pytest.mark.asyncio
async def test_failure_is_swallowed():
    ok = await send_digest_notification(
        NotifyConfig(enabled=True, webhook_url="https://x/hook"), _digest(), _BoomClient())
    assert ok is False   # never raises
