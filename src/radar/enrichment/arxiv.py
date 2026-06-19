"""arXiv paper-mention counts for tracked projects (no API key required).

Counts recent arXiv papers whose text matches a project's curated search
phrase, restricted to the AI-relevant category set, and returns the count plus
the most-recent matching papers as evidence. Mirrors the Hacker News enricher.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

import feedparser
from dateutil import parser as date_parser

from radar.models import PaperRef


ARXIV_API_URL = "http://export.arxiv.org/api/query"
# AI, ML, NLP, distributed, software-eng, vision, robotics. Module constant so
# the searched fields are easy to tune.
ARXIV_CATEGORIES = ["cs.AI", "cs.LG", "cs.CL", "cs.DC", "cs.SE", "cs.CV", "cs.RO"]


class _AsyncClient(Protocol):
    async def get(self, url: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class PaperMentions:
    count: int
    papers: list[PaperRef] = field(default_factory=list)


async def fetch_paper_mentions(
    paper_query: str,
    client: _AsyncClient,
    since: datetime,
    max_papers: int = 5,
) -> PaperMentions:
    """Recent arXiv papers matching ``paper_query`` since a date."""
    cats = " OR ".join(f"cat:{c}" for c in ARXIV_CATEGORIES)
    response = await client.get(
        ARXIV_API_URL,
        params={
            "search_query": f"(all:{paper_query}) AND ({cats})",
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": 0,
            "max_results": 50,
        },
    )
    response.raise_for_status()
    feed = feedparser.parse(response.text)
    papers: list[PaperRef] = []
    for entry in feed.entries:
        published = _published(entry)
        if published is None or published < since:
            continue
        papers.append(
            PaperRef(
                title=(entry.get("title") or "").strip().replace("\n", " "),
                url=entry.get("id") or "",
                published_at=published.date().isoformat(),
            )
        )
    return PaperMentions(count=len(papers), papers=papers[:max_papers])


def _published(entry: Any) -> datetime | None:
    raw = entry.get("published") or entry.get("updated")
    if not raw:
        return None
    try:
        parsed = date_parser.parse(raw)
    except (ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        from datetime import UTC
        return parsed.replace(tzinfo=UTC)
    return parsed
