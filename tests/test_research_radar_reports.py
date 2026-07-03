"""Mover lines + markdown report for techniques."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.models import Category, Ring
from radar.research_radar.entities import OnPremImpact, TechniqueDomain, TechniqueEntry
from radar.research_radar.history import TechniqueHistoryEvent
from radar.research_radar.momentum import MomentumSignal
from radar.research_radar.reports import build_technique_mover_lines, render_technique_report
from radar.storage.history_store import ChangeType


NOW = datetime(2026, 7, 3, 10, 0, tzinfo=UTC)


def _event(technique_id: str, change: ChangeType, ring: Ring,
           previous: Ring | None = None) -> TechniqueHistoryEvent:
    return TechniqueHistoryEvent(
        technique_id=technique_id, domain=TechniqueDomain.INFERENCE, change_type=change,
        ring=ring, previous_ring=previous, run_id="run-1", observed_at=NOW,
    )


def _entry(technique_id: str, ring: Ring) -> TechniqueEntry:
    return TechniqueEntry(
        id=technique_id, name=technique_id.title(), category=Category.MODEL_SERVING,
        domain=TechniqueDomain.INFERENCE, onprem_impact=OnPremImpact.REDUCES_LATENCY,
        ring=ring, citation_count=100,
    )


def test_mover_lines_ring_changes_then_rising():
    events = [
        _event("medusa-decoding", ChangeType.PROMOTED, Ring.PILOT, Ring.WATCH),
        _event("qlora", ChangeType.NEW, Ring.WATCH),
    ]
    momentums = [
        MomentumSignal(technique_id="lora", score=4, direction="rising",
                       citation_growth_pct=12.0),
        MomentumSignal(technique_id="medusa-decoding", score=5, direction="rising"),
        MomentumSignal(technique_id="rag", score=3, direction="steady"),
    ]

    lines = build_technique_mover_lines(events, momentums)

    assert lines[0] == "medusa-decoding: watch → pilot (promoted)"
    assert lines[1] == "qlora: new on the radar (watch)"
    assert any(line.startswith("lora: rising") for line in lines)
    assert not any("medusa-decoding: rising" in line for line in lines)  # no double-report
    assert not any("rag" in line for line in lines)


def test_render_report_contains_movers_and_rings():
    entries = [_entry("speculative-decoding", Ring.ADOPT), _entry("qlora", Ring.WATCH)]

    markdown = render_technique_report(entries, ["qlora: new on the radar (watch)"],
                                       "Research Radar")

    assert "# Research Radar" in markdown
    assert "## Movers" in markdown
    assert "`adopt`" in markdown
    assert "Speculative-Decoding" in markdown or "speculative-decoding" in markdown
