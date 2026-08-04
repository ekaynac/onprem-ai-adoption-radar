"""D5 gate: matching breaking change → Act alert; non-matching → silence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from radar.intelligence.alerts import (
    build_alerts,
    load_demo_profile,
    profile_terms,
)
from radar.intelligence.workspaces import (
    WorkspaceDevice,
    WorkspaceEngine,
    WorkspaceStack,
)


NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def _stack() -> WorkspaceStack:
    return WorkspaceStack(
        engines=[WorkspaceEngine(name="vLLM", version="0.10")],
        models=["Qwen3-32B"],
        quant_formats=["gguf"],
    )


def _devices() -> list[WorkspaceDevice]:
    return [WorkspaceDevice(device_id="rtx-4090-24gb", count=2)]


def _seed_news(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    items = [
        {
            "id": "news:vllm-break",
            "source_id": "vllm-blog",
            "title": "vLLM drops V0 engine",
            "url": "https://blog.vllm.ai/v0-removal",
            "summary": "V0 removed",
            "published_at": "2026-08-02T09:00:00Z",
            "observed_at": "2026-08-02T10:00:00Z",
        },
        {
            "id": "news:sglang-break",
            "source_id": "hn-vllm",
            "title": "SGLang breaking scheduler change",
            "url": "https://example.com/sglang",
            "summary": "Scheduler rewrite",
            "published_at": "2026-08-02T09:00:00Z",
            "observed_at": "2026-08-02T10:00:00Z",
        },
        {
            "id": "news:vllm-info",
            "source_id": "vllm-blog",
            "title": "vLLM community meetup",
            "url": "https://blog.vllm.ai/meetup",
            "summary": "Meetup",
            "published_at": "2026-08-03T09:00:00Z",
            "observed_at": "2026-08-03T10:00:00Z",
        },
        {
            "id": "news:qwen-improve",
            "source_id": "hf-blog",
            "title": "Qwen3 quantized weights refreshed",
            "url": "https://example.com/qwen3",
            "summary": "Better AWQ",
            "published_at": "2026-08-03T09:00:00Z",
            "observed_at": "2026-08-03T10:00:00Z",
        },
    ]
    (data / "news-observations.jsonl").write_text(
        "\n".join(json.dumps(item) for item in items) + "\n"
    )

    def _classification(news_id, components, impact, event_type="release"):
        return {
            "news_id": news_id,
            "relevant": True,
            "event_type": event_type,
            "components": components,
            "operational_impact": impact,
            "summary": f"summary for {news_id}",
            "citation": "https://example.com/cite",
            "model": "claude-opus-5",
            "classified_at": "2026-08-03T12:00:00Z",
        }

    rows = [
        _classification(
            "news:vllm-break", ["vllm"], "breaking", "breaking-change"
        ),
        _classification(
            "news:sglang-break", ["sglang"], "breaking", "breaking-change"
        ),
        _classification("news:vllm-info", ["vllm"], "informational"),
        _classification("news:qwen-improve", ["qwen3"], "improvement"),
    ]
    (data / "news-classified.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n"
    )


def test_matching_breaking_change_is_an_act_alert(tmp_path):
    _seed_news(tmp_path)

    result = build_alerts(
        tmp_path, devices=_devices(), stack=_stack(), now=NOW
    )

    by_id = {alert["id"]: alert for alert in result["alerts"]}
    alert = by_id["alert:news:news:vllm-break"]
    assert alert["verdict"] == "act"
    assert alert["matched_components"] == ["vllm"]
    assert alert["receipts"] == ["https://example.com/cite"]
    assert result["counts"]["act"] == 1


def test_non_matching_and_informational_events_stay_silent(tmp_path):
    _seed_news(tmp_path)

    result = build_alerts(
        tmp_path, devices=_devices(), stack=_stack(), now=NOW
    )

    ids = {alert["id"] for alert in result["alerts"]}
    # SGLang is not in the stack; the meetup is informational.
    assert "alert:news:news:sglang-break" not in ids
    assert "alert:news:news:vllm-info" not in ids


def test_family_prefix_matches_improvements_as_evaluate(tmp_path):
    _seed_news(tmp_path)

    result = build_alerts(
        tmp_path, devices=_devices(), stack=_stack(), now=NOW
    )

    by_id = {alert["id"]: alert for alert in result["alerts"]}
    # Component "qwen3" matches profile model "qwen3-32b" (dash family).
    alert = by_id["alert:news:news:qwen-improve"]
    assert alert["verdict"] == "evaluate"
    assert alert["matched_components"] == ["qwen3-32b"]
    # Act alerts sort before evaluate alerts.
    assert result["alerts"][0]["verdict"] == "act"


def test_ring_move_for_stack_model_alerts(tmp_path):
    _seed_news(tmp_path)
    (tmp_path / "data" / "model-history.jsonl").write_text(
        json.dumps(
            {
                "model_id": "qwen3-32b",
                "family": "Qwen3",
                "change_type": "demoted",
                "ring": "pilot",
                "previous_ring": "adopt",
                "run_id": "run-1",
                "observed_at": "2026-08-02T08:00:00Z",
                "reasons": ["demoted"],
            }
        )
        + "\n"
        + json.dumps(
            {
                "model_id": "phi-4",
                "family": "Phi",
                "change_type": "promoted",
                "ring": "adopt",
                "previous_ring": "pilot",
                "run_id": "run-1",
                "observed_at": "2026-08-02T08:00:00Z",
                "reasons": ["promoted"],
            }
        )
        + "\n"
    )

    result = build_alerts(
        tmp_path, devices=_devices(), stack=_stack(), now=NOW
    )

    ring_alerts = [
        alert for alert in result["alerts"] if alert["source"] == "ring-move"
    ]
    assert len(ring_alerts) == 1
    assert ring_alerts[0]["subject"] == "qwen3-32b"
    assert ring_alerts[0]["verdict"] == "act"  # left adopt


def test_stale_events_are_windowed_out(tmp_path):
    _seed_news(tmp_path)

    result = build_alerts(
        tmp_path,
        devices=_devices(),
        stack=_stack(),
        now=datetime(2026, 9, 30, 12, 0, tzinfo=UTC),
    )

    assert result["alerts"] == []


def test_empty_profile_yields_no_alerts(tmp_path):
    _seed_news(tmp_path)

    result = build_alerts(
        tmp_path, devices=[], stack=WorkspaceStack(), now=NOW
    )

    assert result["alerts"] == []
    assert result["profile_terms"] == []


def test_profile_terms_normalize_case():
    terms = profile_terms(_devices(), _stack())
    assert terms == {"vllm", "qwen3-32b", "gguf", "rtx-4090-24gb"}


def test_shipped_demo_profile_loads_and_resolves():
    profile = load_demo_profile(
        Path(__file__).resolve().parents[1]
        / "config"
        / "stack-profile-demo.yaml"
    )
    assert profile.name.startswith("Mega")
    assert profile.stack.engines
    terms = profile_terms(profile.devices, profile.stack)
    assert "vllm" in terms and "qwen3-32b" in terms
