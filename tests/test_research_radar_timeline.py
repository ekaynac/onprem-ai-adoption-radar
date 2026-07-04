"""Timeline: papers + ring history merged chronologically."""

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
from radar.research_radar.timeline import TimelineItem, build_technique_timeline
from radar.storage.history_store import ChangeType


def _entry(papers: list[PaperLink]) -> TechniqueEntry:
    return TechniqueEntry(
        id="speculative-decoding", name="Speculative Decoding",
        category=Category.MODEL_SERVING, domain=TechniqueDomain.INFERENCE,
        onprem_impact=OnPremImpact.REDUCES_LATENCY, papers=papers,
    )


def _ring_event(technique_id: str, at: str) -> TechniqueHistoryEvent:
    return TechniqueHistoryEvent(
        technique_id=technique_id, domain=TechniqueDomain.INFERENCE,
        change_type=ChangeType.NEW, ring=Ring.ADOPT, run_id="run-1",
        observed_at=datetime.fromisoformat(at),
    )


def test_timeline_merges_papers_and_rings_chronologically():
    papers = [
        PaperLink(arxiv_id="2211.17192", title="Fast Inference", published="2022-11"),
        PaperLink(arxiv_id="2302.01318", title="Spec Sampling",
                  role=PaperRole.FOLLOWUP, published="2023-02"),
    ]
    events = [_ring_event("speculative-decoding", "2026-07-03T10:00:00+00:00")]

    timeline = build_technique_timeline(_entry(papers), events)

    assert [i.kind for i in timeline] == ["paper", "paper", "ring"]
    assert timeline[0] == TimelineItem(
        date="2022-11", label="canonical paper: Fast Inference", kind="paper")
    assert timeline[1].label == "followup paper: Spec Sampling"
    assert timeline[2].date == "2026-07-03"
    assert "adopt" in timeline[2].label and "new" in timeline[2].label


def test_timeline_skips_undated_papers_and_other_techniques():
    papers = [PaperLink(arxiv_id="0000.00000", title="No date")]
    events = [_ring_event("some-other-technique", "2026-07-03T10:00:00+00:00")]

    timeline = build_technique_timeline(_entry(papers), events)

    assert timeline == []


def test_timeline_promotion_label_includes_previous_ring():
    event = TechniqueHistoryEvent(
        technique_id="speculative-decoding", domain=TechniqueDomain.INFERENCE,
        change_type=ChangeType.PROMOTED, ring=Ring.ADOPT, previous_ring=Ring.PILOT,
        run_id="run-2", observed_at=datetime(2026, 7, 4, 10, 0, tzinfo=UTC),
    )

    timeline = build_technique_timeline(_entry([]), [event])

    assert timeline[0].label == "pilot → adopt (promoted)"
