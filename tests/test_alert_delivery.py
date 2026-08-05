"""Alert delivery: exactly-once webhook push for stack-profile alerts."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from typer.testing import CliRunner

from radar.cli import app
from radar.models import NotifyConfig
from radar.notify.alert_delivery import (
    build_alert_slack_text,
    send_alert_notification,
)
from radar.storage.alert_delivery_log import (
    DeliveredAlert,
    append_delivered_alerts,
    load_delivered_alerts,
)


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)

_ALERT = {
    "id": "alert:news:news:vllm-break",
    "source": "news",
    "verdict": "act",
    "subject": "vLLM drops V0 engine",
    "what_happened": "V0 removed; migrate.",
    "matched_components": ["vllm"],
    "event_type": "breaking-change",
    "receipts": ["https://blog.vllm.ai/v0-removal"],
    "observed_at": "2026-08-04T09:00:00Z",
}


class _Resp:
    status_code = 200

    def raise_for_status(self):
        return None


class _Client:
    def __init__(self, fail: bool = False):
        self.posts: list[tuple[str, dict]] = []
        self._fail = fail

    async def post(self, url, json=None):
        if self._fail:
            raise RuntimeError("down")
        self.posts.append((url, json))
        return _Resp()


def _config(**overrides) -> NotifyConfig:
    values = {
        "enabled": True,
        "webhook_url": "https://hooks.example/x",
        "format": "generic",
    }
    values.update(overrides)
    return NotifyConfig(**values)


def test_send_posts_generic_payload_and_never_raises():
    client = _Client()
    sent = asyncio.run(
        send_alert_notification(_config(), [_ALERT], "Demo", client)
    )
    assert sent is True
    url, body = client.posts[0]
    assert url == "https://hooks.example/x"
    assert body["kind"] == "stack-alerts"
    assert body["alerts"][0]["subject"] == "vLLM drops V0 engine"
    # Disabled / empty / failing paths are all quiet no-sends.
    assert (
        asyncio.run(
            send_alert_notification(
                _config(enabled=False), [_ALERT], "Demo", client
            )
        )
        is False
    )
    assert (
        asyncio.run(send_alert_notification(_config(), [], "Demo", client))
        is False
    )
    assert (
        asyncio.run(
            send_alert_notification(_config(), [_ALERT], "Demo", _Client(fail=True))
        )
        is False
    )


def test_slack_text_carries_verdict_and_receipt():
    text = build_alert_slack_text([_ALERT], "Demo")
    assert "[ACT] vLLM drops V0 engine" in text
    assert "https://blog.vllm.ai/v0-removal" in text


def test_delivery_log_is_exactly_once_per_profile(tmp_path):
    path = tmp_path / "alerts-delivered.jsonl"
    row = DeliveredAlert(alert_id="alert:1", profile="Demo", delivered_at=NOW)
    assert append_delivered_alerts(path, [row, row]) == 1
    assert append_delivered_alerts(path, [row]) == 0
    other_profile = row.model_copy(update={"profile": "Other"})
    assert append_delivered_alerts(path, [other_profile]) == 1
    assert len(load_delivered_alerts(path)) == 2


_SOURCES_YAML = """\
sources:
  - id: vllm
    type: github_repo
    project: vLLM
    category: model_serving
    url: https://github.com/vllm-project/vllm
"""


def _seed_alertable_root(tmp_path):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    recent = (NOW.replace(day=4)).isoformat()
    (data / "news-observations.jsonl").write_text(
        json.dumps(
            {
                "id": "news:vllm-break",
                "source_id": "vllm-blog",
                "title": "vLLM drops V0 engine",
                "url": "https://blog.vllm.ai/v0-removal",
                "summary": "V0 removed",
                "published_at": recent,
                "observed_at": recent,
            }
        )
        + "\n"
    )
    (data / "news-classified.jsonl").write_text(
        json.dumps(
            {
                "news_id": "news:vllm-break",
                "relevant": True,
                "event_type": "breaking-change",
                "components": ["vllm"],
                "operational_impact": "breaking",
                "summary": "V0 removed; migrate.",
                "citation": "https://blog.vllm.ai/v0-removal",
                "model": "claude-opus-5",
                "classified_at": recent,
            }
        )
        + "\n"
    )
    (data / "config.yaml").write_text(
        _SOURCES_YAML
        + "notify:\n"
        "  enabled: true\n"
        "  webhook_url: https://hooks.example/x\n"
        "  format: generic\n",
        encoding="utf-8",
    )


def test_cli_delivers_new_alerts_once(tmp_path, monkeypatch):
    _seed_alertable_root(tmp_path)
    sent_bodies: list[dict] = []

    async def _fake_send(config, alerts, profile_name, client):
        sent_bodies.append({"alerts": alerts, "profile": profile_name})
        return True

    monkeypatch.setattr(
        "radar.notify.alert_delivery.send_alert_notification", _fake_send
    )
    runner = CliRunner()

    result = runner.invoke(app, ["alerts", "notify", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "Delivered 1 new alert(s)" in result.stdout
    assert sent_bodies[0]["alerts"][0]["subject"] == "vLLM drops V0 engine"
    assert (
        len(load_delivered_alerts(tmp_path / "data" / "alerts-delivered.jsonl"))
        == 1
    )

    # Second run: nothing new — the webhook is not called again.
    result = runner.invoke(app, ["alerts", "notify", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "No new alerts to deliver" in result.stdout
    assert len(sent_bodies) == 1


def test_cli_skips_visibly_when_notify_disabled(tmp_path):
    _seed_alertable_root(tmp_path)
    (tmp_path / "data" / "config.yaml").write_text(
        _SOURCES_YAML + "notify:\n  enabled: false\n", encoding="utf-8"
    )
    runner = CliRunner()

    result = runner.invoke(app, ["alerts", "notify", "--root", str(tmp_path)])

    assert result.exit_code == 0
    assert "skipped" in result.stdout
    assert not (tmp_path / "data" / "alerts-delivered.jsonl").exists()


def test_annotate_delivery_state_stamps_and_gates(tmp_path):
    from radar.notify.alert_delivery import annotate_delivery_state

    feed = {"alerts": [{"id": "alert:a"}, {"id": "alert:b"}]}
    # No log yet: badges stay hidden, timestamps null.
    annotated = annotate_delivery_state(dict(feed), tmp_path, "Demo")
    assert annotated["delivery_active"] is False
    assert all(a["delivered_at"] is None for a in annotated["alerts"])

    append_delivered_alerts(
        tmp_path / "data" / "alerts-delivered.jsonl",
        [DeliveredAlert(alert_id="alert:a", profile="Demo", delivered_at=NOW)],
    )
    feed = {"alerts": [{"id": "alert:a"}, {"id": "alert:b"}]}
    annotated = annotate_delivery_state(feed, tmp_path, "Demo")
    assert annotated["delivery_active"] is True
    assert annotated["alerts"][0]["delivered_at"] == NOW.isoformat()
    assert annotated["alerts"][1]["delivered_at"] is None
    # A different profile sees none of these deliveries.
    other = annotate_delivery_state(
        {"alerts": [{"id": "alert:a"}]}, tmp_path, "Other"
    )
    assert other["delivery_active"] is False
