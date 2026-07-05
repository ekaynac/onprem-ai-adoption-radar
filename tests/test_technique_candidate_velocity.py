"""Citations/day enrichment for discovery proposals (single-shot velocity proxy)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from radar.discovery.technique_candidate_velocity import (
    enrich_proposals_with_velocity,
    rank_proposals,
)
from radar.discovery.technique_proposals import TechniqueProposal
from radar.models import Category
from radar.research_radar.entities import TechniqueDomain


NOW = datetime(2026, 7, 5, tzinfo=UTC)


def _proposal(arxiv_id: str, published: str | None, upvotes: int = 0) -> TechniqueProposal:
    return TechniqueProposal(
        suggested_id=f"t-{arxiv_id.replace('.', '-')}", name="T", arxiv_id=arxiv_id,
        published=published, upvotes=upvotes,
        suggested_domain=TechniqueDomain.INFERENCE,
        suggested_category=Category.MODEL_SERVING, matched_keyword="inference",
    )


class _FetchOK:
    """Patch target double for fetch_citations."""


@pytest.mark.asyncio
async def test_enrich_computes_citations_per_day(monkeypatch):
    from radar.research_radar.citations import CitationRecord

    async def _fake_fetch(arxiv_ids, client, contact_email=None):
        return {"2606.00001": CitationRecord(
            arxiv_id="2606.00001", citation_count=50, source="s2")}

    monkeypatch.setattr(
        "radar.discovery.technique_candidate_velocity.fetch_citations", _fake_fetch,
    )
    proposals = [_proposal("2606.00001", "2026-06-25")]  # 10 days before NOW

    enriched = await enrich_proposals_with_velocity(proposals, client=None, now=NOW)

    assert enriched[0].citation_count == 50
    assert enriched[0].citations_per_day == 5.0
    assert proposals[0].citation_count is None  # originals untouched (immutability)


@pytest.mark.asyncio
async def test_enrich_month_precision_and_missing_dates(monkeypatch):
    from radar.research_radar.citations import CitationRecord

    async def _fake_fetch(arxiv_ids, client, contact_email=None):
        return {
            "2606.00002": CitationRecord(arxiv_id="2606.00002", citation_count=34,
                                         source="s2"),
            "2606.00003": CitationRecord(arxiv_id="2606.00003", citation_count=7,
                                         source="s2"),
        }

    monkeypatch.setattr(
        "radar.discovery.technique_candidate_velocity.fetch_citations", _fake_fetch,
    )
    proposals = [_proposal("2606.00002", "2026-06"),   # treated as 2026-06-01 → 34 days
                 _proposal("2606.00003", None)]        # no date → velocity None

    enriched = await enrich_proposals_with_velocity(proposals, client=None, now=NOW)

    assert enriched[0].citations_per_day == 1.0
    assert enriched[1].citation_count == 7
    assert enriched[1].citations_per_day is None


@pytest.mark.asyncio
async def test_enrich_degrades_when_fetch_fails(monkeypatch):
    async def _boom(arxiv_ids, client, contact_email=None):
        raise RuntimeError("apis down")

    monkeypatch.setattr(
        "radar.discovery.technique_candidate_velocity.fetch_citations", _boom,
    )
    proposals = [_proposal("2606.00004", "2026-06-25", upvotes=9)]

    enriched = await enrich_proposals_with_velocity(proposals, client=None, now=NOW)

    assert enriched == proposals  # unchanged, no raise


def test_rank_velocity_first_then_upvotes_then_id():
    a = _proposal("2606.00005", "2026-06-25", upvotes=100)
    b = _proposal("2606.00006", "2026-06-25", upvotes=1).model_copy(
        update={"citations_per_day": 9.9, "citation_count": 99})
    c = _proposal("2606.00007", "2026-06-25", upvotes=100)

    ranked = rank_proposals([a, b, c])

    assert ranked[0].arxiv_id == "2606.00006"          # velocity wins
    assert [p.arxiv_id for p in ranked[1:]] == ["2606.00005", "2606.00007"]  # id tiebreak
