"""Track record: paper date → first radar flag lag (the computable-today view)."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.models import Category, Ring
from radar.research_radar.entities import (
    OnPremImpact,
    PaperLink,
    PaperRole,
    TechniqueDomain,
    TechniqueEntry,
)
from radar.research_radar.history import TechniqueHistoryEvent
from radar.research_radar.track_record import build_track_record
from radar.storage.history_store import ChangeType


def _entry(technique_id: str, papers: list[PaperLink], ring: Ring = Ring.PILOT):
    return TechniqueEntry(
        id=technique_id, name=technique_id, category=Category.MODEL_SERVING,
        domain=TechniqueDomain.INFERENCE, onprem_impact=OnPremImpact.REDUCES_LATENCY,
        ring=ring, papers=papers,
    )


def _event(technique_id: str, at: str) -> TechniqueHistoryEvent:
    return TechniqueHistoryEvent(
        technique_id=technique_id, domain=TechniqueDomain.INFERENCE,
        change_type=ChangeType.NEW, ring=Ring.PILOT, run_id="run-1",
        observed_at=datetime.fromisoformat(at),
    )


def test_rows_compute_lag_and_sort():
    entries = [
        _entry("young", [PaperLink(arxiv_id="1", title="t", published="2026-06-01")]),
        _entry("old", [PaperLink(arxiv_id="2", title="t", published="2022-11")]),
        _entry("undated", [PaperLink(arxiv_id="3", title="t")]),
    ]
    events = [
        _event("young", "2026-07-03T10:00:00+00:00"),
        _event("old", "2026-07-03T10:00:00+00:00"),
        _event("old", "2026-07-05T10:00:00+00:00"),  # later event ignored (first wins)
        _event("undated", "2026-07-03T10:00:00+00:00"),
    ]

    rows = build_track_record(entries, events)

    assert [r.technique_id for r in rows] == ["young", "old", "undated"]  # lag asc, None last
    assert rows[0].lag_days == 32
    assert rows[1].first_flagged == "2026-07-03"
    assert rows[1].lag_days == (datetime(2026, 7, 3, tzinfo=UTC)
                                - datetime(2022, 11, 1, tzinfo=UTC)).days
    assert rows[2].lag_days is None


def test_entries_without_events_are_excluded():
    entries = [_entry("never-flagged", [])]

    assert build_track_record(entries, []) == []


def test_only_canonical_paper_counts():
    papers = [
        PaperLink(arxiv_id="1", title="f", role=PaperRole.FOLLOWUP, published="2020-01"),
        PaperLink(arxiv_id="2", title="c", published="2024-01"),
    ]
    rows = build_track_record([_entry("t", papers)],
                              [_event("t", "2026-07-03T10:00:00+00:00")])

    assert rows[0].paper_published == "2024-01"
