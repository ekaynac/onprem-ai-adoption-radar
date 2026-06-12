"""Tests for the append-only JSONL history log (durable source of truth)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from radar.models import Category, Ring
from radar.pipeline.delta import ChangeType
from radar.storage.history_log import append_events, load_events
from radar.storage.history_store import ProjectHistoryEvent


def _event(project: str, day: int, change=ChangeType.NEW, ring=Ring.PILOT) -> ProjectHistoryEvent:
    return ProjectHistoryEvent(
        project=project,
        category=Category.MODEL_SERVING,
        change_type=change,
        ring=ring,
        previous_ring=None,
        run_id=f"run-{day}",
        observed_at=datetime(2026, 6, day, tzinfo=timezone.utc),
        reasons=["because"],
    )


def test_load_missing_file_returns_empty(tmp_path: Path):
    assert load_events(tmp_path / "nope.jsonl") == []


def test_append_then_load_round_trips(tmp_path: Path):
    log = tmp_path / "history.jsonl"
    events = [_event("vLLM", 10), _event("Ollama", 10)]

    append_events(log, events)
    loaded = load_events(log)

    assert [e.project for e in loaded] == ["vLLM", "Ollama"]
    assert loaded[0].change_type == ChangeType.NEW
    assert loaded[0].observed_at == events[0].observed_at


def test_append_is_additive_not_overwriting(tmp_path: Path):
    log = tmp_path / "history.jsonl"
    append_events(log, [_event("vLLM", 10)])
    append_events(log, [_event("vLLM", 12, change=ChangeType.PROMOTED, ring=Ring.ADOPT)])

    loaded = load_events(log)
    assert len(loaded) == 2
    assert [e.change_type for e in loaded] == [ChangeType.NEW, ChangeType.PROMOTED]


def test_append_empty_is_noop(tmp_path: Path):
    log = tmp_path / "history.jsonl"
    append_events(log, [])
    assert load_events(log) == []


def test_log_is_one_json_object_per_line(tmp_path: Path):
    log = tmp_path / "history.jsonl"
    append_events(log, [_event("vLLM", 10), _event("Ollama", 11)])

    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    import json

    for line in lines:
        json.loads(line)  # each line is valid standalone JSON
