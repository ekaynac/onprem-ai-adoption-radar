"""Tests for the append-only per-project observation history (Phase C)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from radar.models import Category, DecisionCard, Ring
from radar.pipeline.delta import CardDelta, ChangeType
from radar.storage.history_store import HistoryStore


def _card(project: str, ring: Ring) -> DecisionCard:
    return DecisionCard(
        project=project,
        category=Category.MODEL_SERVING,
        ring=ring,
        summary="x",
        workflow_fit={},
        risk_level="medium",
    )


def _delta(project: str, change: ChangeType, ring: Ring, prev: Ring | None) -> CardDelta:
    return CardDelta(
        project=project,
        category=Category.MODEL_SERVING,
        change_type=change,
        current_ring=ring,
        previous_ring=prev,
        reasons=["because"],
        card=_card(project, ring),
    )


def _at(day: int) -> datetime:
    return datetime(2026, 6, day, 12, 0, tzinfo=timezone.utc)


def test_record_deltas_appends_events(tmp_path: Path):
    store = HistoryStore(tmp_path / "radar.db")
    store.initialize()

    store.record_deltas(
        [_delta("Ollama", ChangeType.NEW, Ring.WATCH, None)],
        run_id="run-1",
        observed_at=_at(10),
    )

    events = store.history_for("Ollama")
    assert len(events) == 1
    assert events[0].change_type == ChangeType.NEW
    assert events[0].ring == Ring.WATCH
    assert events[0].run_id == "run-1"


def test_history_is_append_only_and_ordered_oldest_first(tmp_path: Path):
    store = HistoryStore(tmp_path / "radar.db")
    store.initialize()

    store.record_deltas(
        [_delta("Ollama", ChangeType.NEW, Ring.WATCH, None)],
        run_id="run-1",
        observed_at=_at(10),
    )
    store.record_deltas(
        [_delta("Ollama", ChangeType.PROMOTED, Ring.PILOT, Ring.WATCH)],
        run_id="run-2",
        observed_at=_at(11),
    )

    events = store.history_for("Ollama")
    assert [e.change_type for e in events] == [ChangeType.NEW, ChangeType.PROMOTED]
    assert events[1].previous_ring == Ring.WATCH
    assert events[0].observed_at < events[1].observed_at


def test_summaries_aggregate_per_project(tmp_path: Path):
    store = HistoryStore(tmp_path / "radar.db")
    store.initialize()
    store.record_deltas(
        [
            _delta("Ollama", ChangeType.NEW, Ring.WATCH, None),
            _delta("vLLM", ChangeType.NEW, Ring.PILOT, None),
        ],
        run_id="run-1",
        observed_at=_at(10),
    )
    store.record_deltas(
        [_delta("Ollama", ChangeType.PROMOTED, Ring.PILOT, Ring.WATCH)],
        run_id="run-2",
        observed_at=_at(12),
    )

    summaries = {s.project: s for s in store.summaries()}
    assert summaries["Ollama"].first_seen == _at(10)
    assert summaries["Ollama"].last_change_at == _at(12)
    assert summaries["Ollama"].change_count == 2
    assert summaries["Ollama"].current_ring == Ring.PILOT
    assert summaries["vLLM"].change_count == 1
    assert summaries["vLLM"].current_ring == Ring.PILOT


def test_empty_deltas_record_nothing(tmp_path: Path):
    store = HistoryStore(tmp_path / "radar.db")
    store.initialize()

    store.record_deltas([], run_id="run-1", observed_at=_at(10))

    assert store.history_for("Ollama") == []
    assert store.summaries() == []
