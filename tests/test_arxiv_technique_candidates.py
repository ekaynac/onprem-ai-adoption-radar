"""arXiv category sweep → keyword-gated technique candidates."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from radar.discovery.arxiv_technique_candidates import discover_arxiv_candidates


FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2607.01111v1</id>
    <title>Blazing Fast KV Cache Inference</title>
    <published>2026-07-02T00:00:00Z</published>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2607.02222v2</id>
    <title>A Dataset of Cats</title>
    <published>2026-07-02T00:00:00Z</published>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2606.03333v1</id>
    <title>Old Agent Planning Paper</title>
    <published>2026-06-01T00:00:00Z</published>
  </entry>
</feed>"""


class _Response:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code
        self.headers: dict[str, str] = {}

    def raise_for_status(self):
        return None


class _Client:
    def __init__(self, text: str | None = FEED_XML, fail: bool = False):
        self._text = text
        self._fail = fail
        self.params: dict | None = None

    async def get(self, url, **kwargs):
        if self._fail:
            raise RuntimeError("arXiv down")
        self.params = kwargs.get("params")
        return _Response(self._text or "")


SINCE = datetime(2026, 6, 28, tzinfo=UTC)


@pytest.mark.asyncio
async def test_sweep_keyword_gates_and_respects_since():
    client = _Client()

    proposals = await discover_arxiv_candidates([], client, since=SINCE)

    assert [p.arxiv_id for p in proposals] == ["2607.01111"]  # cats dropped, old dropped
    proposal = proposals[0]
    assert proposal.discovered_via == "arxiv-sweep"
    assert proposal.upvotes == 0
    assert proposal.published == "2026-07-02"
    assert proposal.suggested_id == "blazing-fast-kv-cache-inference"
    assert "sortBy" in (client.params or {})


@pytest.mark.asyncio
async def test_sweep_dedups_against_seeds():
    from radar.models import Category
    from radar.research_radar.entities import (
        OnPremImpact,
        PaperLink,
        TechniqueDomain,
        TechniqueSeed,
    )

    seed = TechniqueSeed(
        id="kv-cache-quantization", name="x", category=Category.MODEL_SERVING,
        domain=TechniqueDomain.INFERENCE, onprem_impact=OnPremImpact.REDUCES_MEMORY,
        papers=[PaperLink(arxiv_id="2607.01111", title="t")],
    )

    proposals = await discover_arxiv_candidates([seed], _Client(), since=SINCE)

    assert proposals == []


@pytest.mark.asyncio
async def test_sweep_degrades_on_failure():
    assert await discover_arxiv_candidates([], _Client(fail=True), since=SINCE) == []
