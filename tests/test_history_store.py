"""Tests for the append-only per-project observation history (Phase C)."""

from __future__ import annotations

from datetime import UTC, datetime
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
    return datetime(2026, 6, day, 12, 0, tzinfo=UTC)


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


def test_has_events_reflects_state(tmp_path: Path):
    store = HistoryStore(tmp_path / "radar.db")
    store.initialize()
    assert store.has_events() is False

    store.record_deltas(
        [_delta("Ollama", ChangeType.NEW, Ring.WATCH, None)], "run-1", _at(10)
    )
    assert store.has_events() is True


def test_import_events_rebuilds_db_from_events(tmp_path: Path):
    # Simulate a wiped DB rehydrated from the durable log.
    source = HistoryStore(tmp_path / "a.db")
    source.initialize()
    source.record_deltas(
        [_delta("Ollama", ChangeType.NEW, Ring.WATCH, None)], "run-1", _at(10)
    )
    source.record_deltas(
        [_delta("Ollama", ChangeType.PROMOTED, Ring.PILOT, Ring.WATCH)], "run-2", _at(11)
    )
    events = source.history_for("Ollama")

    fresh = HistoryStore(tmp_path / "b.db")
    fresh.initialize()
    inserted = fresh.import_events(events)

    assert inserted == 2
    assert [e.change_type for e in fresh.history_for("Ollama")] == [
        ChangeType.NEW,
        ChangeType.PROMOTED,
    ]


def test_import_events_is_idempotent(tmp_path: Path):
    store = HistoryStore(tmp_path / "radar.db")
    store.initialize()
    store.record_deltas(
        [_delta("Ollama", ChangeType.NEW, Ring.WATCH, None)], "run-1", _at(10)
    )
    events = store.history_for("Ollama")

    # Re-importing the same events must not duplicate rows.
    again = store.import_events(events)

    assert again == 0
    assert len(store.history_for("Ollama")) == 1


def test_seen_projects(tmp_path: Path):
    store = HistoryStore(tmp_path / "radar.db")
    store.initialize()
    store.record_deltas(
        [
            _delta("Ollama", ChangeType.NEW, Ring.WATCH, None),
            _delta("vLLM", ChangeType.NEW, Ring.PILOT, None),
        ],
        "run-1",
        _at(10),
    )

    assert store.seen_projects() == {"Ollama", "vLLM"}


def test_summaries_use_timestamps_not_insertion_order(tmp_path: Path):
    """Logs merged from multiple machines may arrive out of chronological
    order; first_seen/last_change must come from observed_at, not row order."""
    store = HistoryStore(tmp_path / "radar.db")
    store.initialize()
    newest = _delta("vLLM", ChangeType.PROMOTED, Ring.ADOPT, Ring.PILOT)
    oldest = _delta("vLLM", ChangeType.NEW, Ring.PILOT, None)
    store.record_deltas([newest], run_id="run-2", observed_at=_at(12))
    store.record_deltas([oldest], run_id="run-1", observed_at=_at(10))

    summary = store.summaries()[0]

    assert summary.first_seen == _at(10)
    assert summary.last_change_at == _at(12)
    assert summary.current_ring == Ring.ADOPT
    assert summary.last_change_type == ChangeType.PROMOTED


def _event(project, change_type, ring, previous_ring, run_id, corrects=None):
    from datetime import UTC, datetime

    from radar.models import Category, Ring
    from radar.pipeline.delta import ChangeType
    from radar.storage.history_store import ProjectHistoryEvent

    return ProjectHistoryEvent(
        project=project,
        category=Category.MCP_TOOLING,
        change_type=ChangeType(change_type),
        ring=Ring(ring),
        previous_ring=Ring(previous_ring) if previous_ring else None,
        run_id=run_id,
        observed_at=datetime(2026, 7, 1, tzinfo=UTC),
        reasons=[],
        corrects_run_id=corrects,
    )


def test_apply_corrections_drops_artifact_and_marker():
    from radar.storage.history_store import apply_corrections

    events = [
        _event("MCP", "new", "watch", None, "run-a"),
        _event("MCP", "promoted", "pilot", "watch", "run-outage"),   # artifact
        _event("MCP", "demoted", "watch", "pilot", "run-b"),
        _event("MCP", "corrected", "watch", "pilot", "repair:run-outage",
               corrects="run-outage"),
    ]
    effective = apply_corrections(events)
    assert [e.run_id for e in effective] == ["run-a", "run-b"]


def test_summaries_use_effective_view(tmp_path):
    from radar.storage.history_store import HistoryStore

    store = HistoryStore(tmp_path / "radar.db")
    store.initialize()
    store.add_events([
        _event("MCP", "new", "watch", None, "run-a"),
        _event("MCP", "promoted", "adopt", "watch", "run-outage"),
        _event("MCP", "corrected", "watch", "adopt", "repair:run-outage",
               corrects="run-outage"),
    ])
    (summary,) = store.summaries()
    assert summary.current_ring.value == "watch"
    assert summary.change_count == 1


def test_corrects_run_id_roundtrips_through_db_and_jsonl(tmp_path):
    from radar.storage.history_log import append_events, load_events
    from radar.storage.history_store import HistoryStore

    marker = _event("MCP", "corrected", "watch", "adopt", "repair:run-x", corrects="run-x")
    store = HistoryStore(tmp_path / "radar.db")
    store.initialize()
    store.add_events([marker])
    assert store.all_events()[0].corrects_run_id == "run-x"

    log = tmp_path / "history.jsonl"
    append_events(log, [marker])
    assert load_events(log)[0].corrects_run_id == "run-x"


def test_all_summaries_includes_project_absent_from_summaries(tmp_path):
    """A project whose entire history was corrected away (a promoted event
    plus the corrected marker that neutralizes it, and nothing else) has no
    effective events, so `summaries()` — used for scoring/momentum — omits it
    entirely. Raw timeline surfaces must never drop a project like this, so
    `all_summaries()` is the enumeration primitive they use instead."""
    from radar.storage.history_store import HistoryStore

    store = HistoryStore(tmp_path / "radar.db")
    store.initialize()
    store.add_events([
        _event("Outaged", "promoted", "adopt", "watch", "run-outage"),
        _event("Outaged", "corrected", "watch", "adopt", "repair:run-outage",
               corrects="run-outage"),
    ])

    assert store.summaries() == []

    (summary,) = store.all_summaries()
    assert summary.project == "Outaged"
    assert summary.change_count == 2  # both raw events counted, nothing dropped


def test_all_summaries_keeps_fully_corrected_project_in_history_report(tmp_path):
    """End-to-end: a fully-corrected project still renders on the raw
    timeline (the cumulative Adoption History report), even though it is
    absent from `summaries()`."""
    from radar.reports.history import render_history_report
    from radar.storage.history_store import HistoryStore

    store = HistoryStore(tmp_path / "radar.db")
    store.initialize()
    store.add_events([
        _event("Outaged", "promoted", "adopt", "watch", "run-outage"),
        _event("Outaged", "corrected", "watch", "adopt", "repair:run-outage",
               corrects="run-outage"),
    ])

    all_summaries = store.all_summaries()
    report = render_history_report(
        summaries=all_summaries,
        events_by_project={"Outaged": store.history_for("Outaged")},
        title="Adoption History",
    )

    assert "Outaged" in report
    assert "corrected" in report
