"""Tests for the post-scan webhook notifier."""

from __future__ import annotations

import pytest

from radar.models import Category, Ring
from radar.notify.webhook import NotifyConfig, build_payload, build_slack_text, send_notification
from radar.pipeline.delta import CardDelta, ChangeType


def _card(project: str, ring: Ring):
    from radar.models import DecisionCard

    return DecisionCard(
        project=project, category=Category.MODEL_SERVING, ring=ring,
        summary="s", workflow_fit={}, risk_level="low",
    )


def _delta(project: str, change: ChangeType, prev: Ring | None, cur: Ring):
    return CardDelta(
        project=project, category=Category.MODEL_SERVING, change_type=change,
        previous_ring=prev, current_ring=cur, reasons=["because"],
        card=_card(project, cur),
    )


class RecordingClient:
    def __init__(self):
        self.calls = []

    async def post(self, url, json=None, **kwargs):
        self.calls.append((url, json))

        class _Resp:
            def raise_for_status(self_inner):
                return None

        return _Resp()


class FailingClient:
    async def post(self, url, **kwargs):
        raise RuntimeError("connection refused")


def test_build_payload_only_includes_ring_changes():
    deltas = [
        _delta("vLLM", ChangeType.PROMOTED, Ring.PILOT, Ring.ADOPT),
        _delta("Steady", ChangeType.UPDATED, Ring.PILOT, Ring.PILOT),
    ]

    payload = build_payload(deltas, run_id="run-1")

    assert payload["run_id"] == "run-1"
    projects = [c["project"] for c in payload["changes"]]
    assert "vLLM" in projects
    assert "Steady" not in projects  # no ring move


def test_build_slack_text_summarizes_moves():
    deltas = [_delta("vLLM", ChangeType.PROMOTED, Ring.PILOT, Ring.ADOPT)]

    text = build_slack_text(deltas, run_id="run-1")

    assert "vLLM" in text
    assert "pilot" in text and "adopt" in text


@pytest.mark.asyncio
async def test_send_notification_posts_generic_payload():
    client = RecordingClient()
    config = NotifyConfig(enabled=True, webhook_url="https://hooks.example/x", format="generic")
    deltas = [_delta("vLLM", ChangeType.PROMOTED, Ring.PILOT, Ring.ADOPT)]

    sent = await send_notification(config, deltas, run_id="run-1", client=client)

    assert sent is True
    url, body = client.calls[0]
    assert url == "https://hooks.example/x"
    assert body["changes"][0]["project"] == "vLLM"


@pytest.mark.asyncio
async def test_send_notification_slack_format_uses_text_field():
    client = RecordingClient()
    config = NotifyConfig(enabled=True, webhook_url="https://hooks.slack/x", format="slack")
    deltas = [_delta("vLLM", ChangeType.DEMOTED, Ring.ADOPT, Ring.WATCH)]

    await send_notification(config, deltas, run_id="run-1", client=client)

    _url, body = client.calls[0]
    assert "text" in body and "vLLM" in body["text"]


@pytest.mark.asyncio
async def test_send_notification_disabled_is_noop():
    client = RecordingClient()
    config = NotifyConfig(enabled=False, webhook_url="https://hooks.example/x")

    sent = await send_notification(
        config,
        [_delta("vLLM", ChangeType.PROMOTED, Ring.PILOT, Ring.ADOPT)],
        run_id="run-1",
        client=client,
    )

    assert sent is False
    assert client.calls == []


@pytest.mark.asyncio
async def test_send_notification_skips_when_no_ring_changes():
    client = RecordingClient()
    config = NotifyConfig(enabled=True, webhook_url="https://hooks.example/x")

    sent = await send_notification(
        config,
        [_delta("vLLM", ChangeType.UPDATED, Ring.PILOT, Ring.PILOT)],
        run_id="run-1",
        client=client,
    )

    assert sent is False
    assert client.calls == []


@pytest.mark.asyncio
async def test_send_notification_degrades_on_failure(caplog):
    import logging

    config = NotifyConfig(enabled=True, webhook_url="https://hooks.example/x")
    deltas = [_delta("vLLM", ChangeType.PROMOTED, Ring.PILOT, Ring.ADOPT)]

    with caplog.at_level(logging.WARNING):
        sent = await send_notification(config, deltas, run_id="run-1", client=FailingClient())

    assert sent is False
    assert caplog.records  # logged, not raised


@pytest.mark.asyncio
async def test_send_notification_without_url_is_noop():
    client = RecordingClient()
    config = NotifyConfig(enabled=True, webhook_url="")

    sent = await send_notification(
        config,
        [_delta("vLLM", ChangeType.PROMOTED, Ring.PILOT, Ring.ADOPT)],
        run_id="run-1",
        client=client,
    )

    assert sent is False
    assert client.calls == []


def test_teams_format_wraps_text_in_adaptive_card():
    """Teams Workflows webhooks silently drop plain {"text": ...} posts."""
    import asyncio

    from radar.models import NotifyConfig
    from radar.notify.webhook import teams_message, text_body

    body = teams_message("hello")
    assert body["type"] == "message"
    card = body["attachments"][0]
    assert card["contentType"] == "application/vnd.microsoft.card.adaptive"
    assert card["content"]["body"][0]["text"] == "hello"
    assert card["content"]["body"][0]["wrap"] is True

    teams = NotifyConfig(
        enabled=True, webhook_url="https://hooks.example/x", format="teams"
    )
    slack = NotifyConfig(
        enabled=True, webhook_url="https://hooks.example/x", format="slack"
    )
    assert text_body(teams, "hi") == teams_message("hi")
    assert text_body(slack, "hi") == {"text": "hi"}

    # The alert sender speaks the same dialect.
    from radar.notify.alert_delivery import send_alert_notification

    class _Resp:
        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self):
            self.bodies = []

        async def post(self, url, json=None):
            self.bodies.append(json)
            return _Resp()

    client = _Client()
    alert = {
        "id": "alert:1",
        "verdict": "act",
        "subject": "vLLM drops V0",
        "what_happened": "migrate",
        "matched_components": ["vllm"],
        "receipts": [],
        "observed_at": "2026-08-04T09:00:00Z",
    }
    assert asyncio.run(
        send_alert_notification(teams, [alert], "Demo", client)
    )
    assert client.bodies[0]["type"] == "message"
    assert "vLLM drops V0" in str(client.bodies[0]["attachments"])


def test_notify_format_validator_accepts_teams_only_known():
    import pytest

    from radar.models import NotifyConfig

    assert NotifyConfig(format="teams").format == "teams"
    with pytest.raises(ValueError):
        NotifyConfig(format="msteams")


def test_rich_teams_alert_card_links_and_button():
    """Bare URLs aren't clickable in Teams cards — markdown + button are."""
    import asyncio

    from radar.models import NotifyConfig
    from radar.notify.alert_delivery import (
        build_alert_teams_message,
        send_alert_notification,
    )

    base = "https://ekaynac.github.io/onprem-ai-adoption-radar"
    ring = {
        "id": "alert:ring:deepseek-r1:2026-08-04T17:00:00Z",
        "verdict": "evaluate",
        "subject": "deepseek-r1",
        "what_happened": "Ring watch → pilot (promoted)",
        "matched_components": ["deepseek-r1"],
        "event_type": "ring-move",
        "receipts": ["data/model-history.jsonl"],
        "observed_at": "2026-08-04T17:00:00Z",
    }
    news = {
        "id": "alert:news:1",
        "verdict": "act",
        "subject": "vLLM drops V0",
        "what_happened": "migrate",
        "matched_components": ["vllm"],
        "event_type": "breaking-change",
        "receipts": ["https://blog.vllm.ai/v0-removal"],
        "observed_at": "2026-08-04T09:00:00Z",
    }

    message = build_alert_teams_message([ring, news], "Demo", base)
    card = message["attachments"][0]["content"]
    text = card["body"][0]["text"]
    assert f"[details ↗]({base}/#/catalog/deepseek-r1)" in text
    assert "[details ↗](https://blog.vllm.ai/v0-removal)" in text
    assert card["actions"] == [
        {
            "type": "Action.OpenUrl",
            "title": "Open radar feed",
            "url": f"{base}/#/workspaces",
        }
    ]
    # Without a base URL: no button, news keeps its receipt link.
    bare = build_alert_teams_message([ring, news], "Demo")
    assert "actions" not in bare["attachments"][0]["content"]
    assert "data/model-history.jsonl" not in str(bare)

    class _Resp:
        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self):
            self.bodies = []

        async def post(self, url, json=None):
            self.bodies.append(json)
            return _Resp()

    teams = NotifyConfig(
        enabled=True, webhook_url="https://hooks.example/x", format="teams"
    )
    client = _Client()
    assert asyncio.run(
        send_alert_notification(teams, [ring], "Demo", client, base)
    )
    assert client.bodies[0]["attachments"][0]["content"]["actions"]
