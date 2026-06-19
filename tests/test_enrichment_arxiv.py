from datetime import UTC, datetime
from typing import Any

import pytest

from radar.enrichment.arxiv import ARXIV_CATEGORIES, fetch_paper_mentions


ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
 <entry><title>Recent vLLM paper</title>
  <id>http://arxiv.org/abs/2506.0002</id>
  <published>2026-06-15T00:00:00Z</published></entry>
 <entry><title>Older vLLM paper</title>
  <id>http://arxiv.org/abs/2505.0001</id>
  <published>2026-05-01T00:00:00Z</published></entry>
</feed>"""


class FakeResp:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        pass


class FakeClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.params: dict[str, Any] | None = None

    async def get(self, url: str, params: dict[str, Any] | None = None, **kw: Any) -> FakeResp:
        self.params = params
        return FakeResp(self.text)


@pytest.mark.asyncio
async def test_counts_and_caps_recent_papers():
    client = FakeClient(ATOM)
    result = await fetch_paper_mentions('"vLLM"', client, since=datetime(2026, 6, 1, tzinfo=UTC))
    # Only the 2026-06-15 entry is within the since window.
    assert result.count == 1
    assert result.papers[0].title == "Recent vLLM paper"
    assert result.papers[0].url == "http://arxiv.org/abs/2506.0002"
    # Query restricts to the AI category set.
    assert client.params is not None
    assert "cat:cs.AI" in client.params["search_query"]
    assert '"vLLM"' in client.params["search_query"]


@pytest.mark.asyncio
async def test_cap_limits_named_papers():
    entries = "".join(
        f'<entry><title>P{i}</title><id>http://arxiv.org/abs/2506.{i}</id>'
        f'<published>2026-06-1{i}T00:00:00Z</published></entry>' for i in range(7)
    )
    client = FakeClient(f'<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>')
    result = await fetch_paper_mentions('"x"', client, since=datetime(2026, 6, 1, tzinfo=UTC), max_papers=5)
    assert result.count == 7
    assert len(result.papers) == 5


def test_category_set_includes_vision_and_robotics():
    assert "cs.CV" in ARXIV_CATEGORIES and "cs.RO" in ARXIV_CATEGORIES
