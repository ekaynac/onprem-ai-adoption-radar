"""Sweep untracked HF/arXiv paper candidates → observations (monkeypatched fetchers)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from radar.discovery import (
    arxiv_technique_candidates,
    hf_technique_candidates,
    technique_candidate_velocity,
)
from radar.discovery.technique_candidate_sweep import sweep_technique_candidates
from radar.discovery.technique_proposals import TechniqueProposal


NOW = datetime(2026, 7, 8, 7, 0, tzinfo=UTC)


def _proposal(arxiv: str, upvotes: int, via: str) -> TechniqueProposal:
    return TechniqueProposal(
        suggested_id=f"t-{arxiv}", name=f"Paper {arxiv}", arxiv_id=arxiv, published="2026-06-20",
        upvotes=upvotes, suggested_domain="agent_architecture", suggested_category="agent_frameworks",
        matched_keyword="reasoning", discovered_via=via, citation_count=5, citations_per_day=1.0,
    )


@pytest.mark.asyncio
async def test_sweep_maps_and_dedups_hf_wins(monkeypatch):
    async def _hf(seeds, client, **kw):
        return [_proposal("2501.dup", 120, "hf-daily-papers"), _proposal("2501.hf", 80, "hf-daily-papers")]

    async def _arxiv(seeds, client, since, **kw):
        return [_proposal("2501.dup", 5, "arxiv"), _proposal("2501.ax", 0, "arxiv")]  # dup → HF wins

    async def _enrich(proposals, client, now, contact_email=None):
        return proposals  # citations already on the fixtures

    monkeypatch.setattr(hf_technique_candidates, "discover_technique_candidates", _hf)
    monkeypatch.setattr(arxiv_technique_candidates, "discover_arxiv_candidates", _arxiv)
    monkeypatch.setattr(technique_candidate_velocity, "enrich_proposals_with_velocity", _enrich)

    rows = await sweep_technique_candidates([], object(), NOW)

    by_id = {r.arxiv_id: r for r in rows}
    assert set(by_id) == {"2501.dup", "2501.hf", "2501.ax"}      # deduped
    assert by_id["2501.dup"].upvotes == 120                       # HF won the duplicate
    assert by_id["2501.hf"].observed_at == NOW
    assert by_id["2501.hf"].suggested_domain == "agent_architecture"


@pytest.mark.asyncio
async def test_sweep_fetch_failure_degrades_empty(monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(hf_technique_candidates, "discover_technique_candidates", _boom)
    monkeypatch.setattr(arxiv_technique_candidates, "discover_arxiv_candidates", _boom)
    # the sweep must not raise even if a fetcher does — mirror discover's best-effort intent
    rows = await sweep_technique_candidates([], object(), NOW)
    assert rows == []
