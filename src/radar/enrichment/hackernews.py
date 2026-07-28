"""Hacker News mention counts via the Algolia search API (no key required)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from radar.enrichment.retry import get_with_retry


HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"


class _AsyncClient(Protocol):
    async def get(self, url: str, **kwargs: Any) -> Any: ...


async def fetch_hn_mentions(
    project: str,
    client: _AsyncClient,
    since: datetime,
) -> int:
    """Number of HN stories mentioning the exact project name since a date."""
    response = await get_with_retry(
        client,
        HN_SEARCH_URL,
        label=f"hackernews {project}",
        params={
            "query": f'"{project}"',  # quoted: exact-phrase match
            "tags": "story",
            "numericFilters": f"created_at_i>{int(since.timestamp())}",
            "hitsPerPage": 0,  # only the count is needed
        },
    )
    payload = response.json()
    return int(payload.get("nbHits") or 0)
