"""Index banner summary of the technique catalog (mirror of models_summary)."""

from __future__ import annotations

from radar.models import Category, Ring
from radar.research_radar.entities import OnPremImpact, TechniqueDomain, TechniqueEntry
from radar.web.research_summary import TechniquesSummary, summarize_techniques


def _entry(technique_id: str, ring: Ring | None, domain: TechniqueDomain) -> TechniqueEntry:
    return TechniqueEntry(
        id=technique_id, name=technique_id, category=Category.MODEL_SERVING,
        domain=domain, onprem_impact=OnPremImpact.REDUCES_LATENCY, ring=ring,
    )


def test_summarize_counts_rings_and_domains():
    summary = summarize_techniques([
        _entry("a", Ring.ADOPT, TechniqueDomain.INFERENCE),
        _entry("b", Ring.PILOT, TechniqueDomain.INFERENCE),
        _entry("c", Ring.WATCH, TechniqueDomain.RAG),
        _entry("d", None, TechniqueDomain.RAG),
    ])

    assert summary.total == 4
    assert summary.by_ring == {"adopt": 1, "pilot": 1, "watch": 1}
    assert summary.by_domain == {"inference": 2, "rag": 2}
    assert summary.has_techniques is True
    assert "4 techniques" in summary.one_line


def test_empty_summary_has_no_techniques():
    summary = summarize_techniques([])

    assert summary == TechniquesSummary()
    assert summary.has_techniques is False
