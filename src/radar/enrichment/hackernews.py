"""Hacker News mention counts via the Algolia search API (no key required)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"


class _AsyncClient(Protocol):
    async def get(self, url: str, **kwargs: Any) -> Any: ...


async def fetch_hn_mentions(
    project: str,
    client: _AsyncClient,
    since: datetime,
) -> int:
    """Number of HN stories mentioning the exact project name since a date."""
    response = await client.get(
        HN_SEARCH_URL,
        params={
            "query": f'"{project}"',  # quoted: exact-phrase match
            "tags": "story",
            "numericFilters": f"created_at_i>{int(since.timestamp())}",
            "hitsPerPage": 0,  # only the count is needed
        },
    )
    response.raise_for_status()
    payload = response.json()
    return int(payload.get("nbHits") or 0)
