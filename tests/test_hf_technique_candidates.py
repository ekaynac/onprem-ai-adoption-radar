"""HF daily-papers → keyword-gated technique candidates."""

from __future__ import annotations

import pytest

from radar.discovery.hf_technique_candidates import (
    discover_technique_candidates,
    match_keyword,
)
from radar.models import Category
from radar.research_radar.entities import PaperLink, TechniqueDomain, TechniqueSeed


class _Response:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.headers: dict[str, str] = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _Client:
    def __init__(self, payload=None, fail: bool = False):
        self._payload = payload or []
        self._fail = fail

    async def get(self, url, **kwargs):
        if self._fail:
            raise RuntimeError("HF down")
        return _Response(self._payload)


def _paper(arxiv_id: str, title: str, upvotes: int, published: str = "2026-07-01T00:00:00Z"):
    return {"paper": {"id": arxiv_id, "title": title, "upvotes": upvotes,
                      "publishedAt": published}}


def _seed(technique_id: str, arxiv_id: str) -> TechniqueSeed:
    from radar.research_radar.entities import OnPremImpact

    return TechniqueSeed(
        id=technique_id, name=technique_id, category=Category.MODEL_SERVING,
        domain=TechniqueDomain.INFERENCE, onprem_impact=OnPremImpact.REDUCES_LATENCY,
        papers=[PaperLink(arxiv_id=arxiv_id, title="t")],
    )


def test_match_keyword_first_entry_wins_and_none_drops():
    keyword, domain, category = match_keyword("Fast Speculative Decoding for LLMs")

    assert keyword == "decoding"
    assert domain == TechniqueDomain.INFERENCE
    assert category == Category.MODEL_SERVING
    assert match_keyword("A New Image Dataset") is None


@pytest.mark.asyncio
async def test_discover_filters_maps_sorts_and_caps():
    payload = [
        _paper("2507.00001", "Ultra-Fast KV Cache Compression", upvotes=90),
        _paper("2507.00002", "A Boring Dataset Paper", upvotes=500),      # no keyword → drop
        _paper("2507.00003", "Agent Planning with Memory", upvotes=40),
        _paper("2507.00004", "Tiny Inference Trick", upvotes=3),          # below floor → drop
    ]

    proposals = await discover_technique_candidates([], _Client(payload), min_upvotes=10)

    assert [p.arxiv_id for p in proposals] == ["2507.00001", "2507.00003"]  # upvotes desc
    assert proposals[0].suggested_domain == TechniqueDomain.INFERENCE
    assert proposals[0].suggested_id == "ultra-fast-kv-cache-compression"
    assert proposals[0].published == "2026-07-01"
    assert proposals[1].suggested_category == Category.AGENT_FRAMEWORKS


@pytest.mark.asyncio
async def test_discover_dedups_against_seed_papers_and_ids():
    payload = [
        _paper("2211.17192", "Even Faster Speculative Decoding", upvotes=99),  # known arxiv id
        _paper("2507.00005", "Known Slug Inference Method", upvotes=50),
    ]
    seeds = [
        _seed("spec-dec", "2211.17192"),
        _seed("known-slug-inference-method", "1111.11111"),
    ]

    proposals = await discover_technique_candidates(seeds, _Client(payload), min_upvotes=10)

    assert proposals == []


@pytest.mark.asyncio
async def test_discover_degrades_to_empty_on_api_failure():
    assert await discover_technique_candidates([], _Client(fail=True)) == []


@pytest.mark.asyncio
async def test_discover_limit_caps_output():
    payload = [_paper(f"2507.{i:05d}", f"Inference Trick {i}", upvotes=100 - i)
               for i in range(30)]

    proposals = await discover_technique_candidates([], _Client(payload), limit=5)

    assert len(proposals) == 5
