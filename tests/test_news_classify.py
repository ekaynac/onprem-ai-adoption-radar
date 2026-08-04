"""Classifier contract: valid JSON in, budget caps, failures stay out."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from radar.discovery.news_classify import (
    NewsClassificationPayload,
    classify_news,
)
from radar.discovery.news_sweep import NewsClassificationConfig
from radar.storage.news_log import NewsItem, news_id_for


NOW = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)


def _config(max_items: int = 25) -> NewsClassificationConfig:
    return NewsClassificationConfig(
        enabled=True,
        model="claude-opus-5",
        max_items_per_run=max_items,
        max_output_tokens=1024,
    )


def _item(url: str) -> NewsItem:
    return NewsItem(
        id=news_id_for(url),
        source_id="vllm-blog",
        title="vLLM v0.10 released",
        url=url,
        summary="Release notes",
        published_at=NOW,
        observed_at=NOW,
    )


class _Block:
    type = "text"

    def __init__(self, text: str):
        self.text = text


class _Response:
    def __init__(self, text: str | None, stop_reason: str = "end_turn"):
        self.stop_reason = stop_reason
        self.content = [] if text is None else [_Block(text)]


_VALID = json.dumps(
    {
        "relevant": True,
        "event_type": "release",
        "components": ["vllm"],
        "operational_impact": "improvement",
        "summary": "New vLLM release worth adopting.",
        "citation": "https://blog.vllm.ai/v0-10",
    }
)


class _Messages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self._responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeClient:
    def __init__(self, responses):
        self.messages = _Messages(responses)


def test_valid_output_becomes_classification():
    client = _FakeClient([_Response(_VALID)])
    result = classify_news(
        [_item("https://blog.vllm.ai/v0-10")], _config(), client, NOW
    )
    assert result.failures == []
    row = result.classifications[0]
    assert row.event_type == "release"
    assert row.operational_impact == "improvement"
    assert row.model == "claude-opus-5"
    assert row.classified_at == NOW
    call = client.messages.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["output_config"]["format"]["type"] == "json_schema"
    schema = call["output_config"]["format"]["schema"]
    assert schema["additionalProperties"] is False


def test_invalid_json_and_bad_schema_stay_unclassified():
    client = _FakeClient(
        [
            _Response("not json at all"),
            _Response(json.dumps({"relevant": True})),
            _Response(_VALID, stop_reason="refusal"),
        ]
    )
    items = [
        _item("https://a.example"),
        _item("https://b.example"),
        _item("https://c.example"),
    ]
    result = classify_news(items, _config(), client, NOW)
    assert result.classifications == []
    assert len(result.failures) == 3
    assert "refusal" in result.failures[2][1]


def test_budget_caps_calls_and_reports_overflow():
    client = _FakeClient([_Response(_VALID), _Response(_VALID)])
    items = [
        _item("https://a.example"),
        _item("https://b.example"),
        _item("https://c.example"),
    ]
    result = classify_news(items, _config(max_items=2), client, NOW)
    assert len(result.classifications) == 2
    assert result.over_budget == 1
    assert len(client.messages.calls) == 2


def test_call_failure_does_not_abort_remaining_items():
    client = _FakeClient([RuntimeError("boom"), _Response(_VALID)])
    items = [_item("https://a.example"), _item("https://b.example")]
    result = classify_news(items, _config(), client, NOW)
    assert len(result.classifications) == 1
    assert len(result.failures) == 1


def test_authentication_error_aborts_the_run():
    import anthropic
    import httpx

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.AuthenticationError(
        "bad key",
        response=httpx.Response(401, request=request),
        body=None,
    )
    client = _FakeClient([error, _Response(_VALID)])
    items = [_item("https://a.example"), _item("https://b.example")]
    result = classify_news(items, _config(), client, NOW)
    assert result.classifications == []
    assert len(result.failures) == 1
    assert len(client.messages.calls) == 1


def test_payload_schema_is_strict():
    schema = NewsClassificationPayload.model_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "relevant",
        "event_type",
        "components",
        "operational_impact",
        "summary",
        "citation",
    }


def test_build_client_without_key_returns_none(monkeypatch):
    from radar.discovery.news_classify import build_anthropic_client

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert build_anthropic_client() is None
