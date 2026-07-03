"""Citation enrichment: S2 batch primary, OpenAlex batch fallback, {} on total failure."""

import pytest

from radar.research_radar.citations import (
    OPENALEX_WORKS_URL,
    S2_BATCH_URL,
    CitationRecord,
    fetch_citations,
)


class _Response:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.headers: dict[str, str] = {}

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    """Programmable fake: maps (method, url-prefix) to a queue of responses."""

    def __init__(self, post_responses=None, get_responses=None):
        self._post = list(post_responses or [])
        self._get = list(get_responses or [])
        self.post_urls: list[str] = []
        self.get_urls: list[str] = []
        self.post_bodies: list[dict] = []
        self.get_params: list[dict] = []

    async def post(self, url: str, **kwargs):
        self.post_urls.append(url)
        self.post_bodies.append(kwargs.get("json") or {})
        if not self._post:
            raise RuntimeError("connection failed")
        return self._post.pop(0)

    async def get(self, url: str, **kwargs):
        self.get_urls.append(url)
        self.get_params.append(kwargs.get("params") or {})
        if not self._get:
            raise RuntimeError("connection failed")
        return self._get.pop(0)


S2_OK = _Response([
    {"paperId": "abc", "venue": "International Conference on Machine Learning",
     "citationCount": 1697},
    None,  # unmatched id comes back as null
    {"paperId": "def", "venue": "", "citationCount": 12},
])


@pytest.mark.asyncio
async def test_s2_batch_happy_path_maps_by_request_order():
    client = _Client(post_responses=[S2_OK])

    records = await fetch_citations(["2211.17192", "9999.00000", "2305.14314"], client)

    assert client.post_urls == [S2_BATCH_URL]
    assert client.post_bodies[0] == {
        "ids": ["ARXIV:2211.17192", "ARXIV:9999.00000", "ARXIV:2305.14314"]
    }
    assert records["2211.17192"] == CitationRecord(
        arxiv_id="2211.17192", citation_count=1697,
        venue="International Conference on Machine Learning",
        peer_reviewed=True, source="s2",
    )
    assert "9999.00000" not in records  # null entry skipped
    assert records["2305.14314"].peer_reviewed is False  # empty venue = preprint


@pytest.mark.asyncio
async def test_s2_venue_arxiv_is_not_peer_reviewed():
    client = _Client(post_responses=[_Response([
        {"paperId": "x", "venue": "arXiv.org", "citationCount": 40},
    ])])

    records = await fetch_citations(["2305.18290"], client)

    assert records["2305.18290"].peer_reviewed is False


OPENALEX_OK = _Response({"results": [
    {"doi": "https://doi.org/10.48550/arxiv.2211.17192", "cited_by_count": 34,
     "primary_location": {"source": {"display_name": "arXiv (Cornell University)"}}},
]})


@pytest.mark.asyncio
async def test_openalex_fallback_when_s2_fails():
    client = _Client(post_responses=[], get_responses=[OPENALEX_OK])

    records = await fetch_citations(["2211.17192"], client)

    assert client.get_urls == [OPENALEX_WORKS_URL]
    assert "doi:10.48550/arXiv.2211.17192" in client.get_params[0]["filter"]
    record = records["2211.17192"]
    assert record.citation_count == 34
    assert record.source == "openalex"
    assert record.peer_reviewed is False  # arXiv repository = preprint


@pytest.mark.asyncio
async def test_openalex_mailto_forwarded():
    client = _Client(post_responses=[], get_responses=[OPENALEX_OK])

    await fetch_citations(["2211.17192"], client, contact_email="radar@mega.com.tr")

    assert client.get_params[0]["mailto"] == "radar@mega.com.tr"


@pytest.mark.asyncio
async def test_both_apis_down_returns_empty():
    client = _Client(post_responses=[], get_responses=[])

    records = await fetch_citations(["2211.17192"], client)

    assert records == {}


@pytest.mark.asyncio
async def test_empty_input_makes_no_requests():
    client = _Client()

    records = await fetch_citations([], client)

    assert records == {}
    assert client.post_urls == []
    assert client.get_urls == []


@pytest.mark.asyncio
async def test_openalex_keeps_earlier_chunks_when_later_chunk_fails():
    """>50 ids = 2 chunks; the second chunk's failure must not discard the first."""
    ids = [f"24{i:02d}.{i:05d}" for i in range(51)]
    ok_first_chunk = _Response({"results": [
        {"doi": "https://doi.org/10.48550/arxiv." + ids[0], "cited_by_count": 7,
         "primary_location": {"source": {"display_name": "arXiv (Cornell University)"}}},
    ]})
    client = _Client(post_responses=[], get_responses=[ok_first_chunk])  # 2nd get raises

    records = await fetch_citations(ids, client)

    assert len(client.get_urls) == 2  # both chunks attempted
    assert records[ids[0]].citation_count == 7
