"""Discover candidate techniques from a recent arXiv category sweep.

Same keyword gate as the HF daily-papers source (no triage fallback — raw
arXiv listings are far noisier than HF's curated feed, so unmatched titles
are dropped). arXiv has no popularity signal; candidates carry upvotes=0 and
rely on the citations/day enrichment for ranking. Failures degrade to "no
proposals". Human-gated like every discovery source.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

import feedparser
from dateutil import parser as date_parser

from radar.discovery.hf_technique_candidates import match_keyword
from radar.discovery.technique_proposals import TechniqueProposal
from radar.enrichment.arxiv import ARXIV_API_URL, ARXIV_CATEGORIES
from radar.enrichment.retry import get_with_retry
from radar.research_radar.entities import TechniqueSeed
from radar.web.slugs import project_slug


logger = logging.getLogger(__name__)

_ABS_ID_RE = re.compile(r"arxiv\.org/abs/(\d{4}\.\d{4,5})")
_SWEEP_MAX_RESULTS = 100


async def discover_arxiv_candidates(
    seeds: list[TechniqueSeed],
    client: Any,
    since: datetime,
    limit: int = 20,
) -> list[TechniqueProposal]:
    known_arxiv = {p.arxiv_id for s in seeds for p in s.papers}
    known_ids = {s.id for s in seeds}
    try:
        cats = " OR ".join(f"cat:{c}" for c in ARXIV_CATEGORIES)
        response = await get_with_retry(
            client,
            ARXIV_API_URL,
            label="arxiv-sweep",
            params={
                "search_query": cats,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "start": 0,
                "max_results": _SWEEP_MAX_RESULTS,
            },
            follow_redirects=True,
        )
        entries = feedparser.parse(response.text).entries
    except Exception as exc:
        logger.warning("arXiv sweep failed: %s", exc)
        return []

    by_arxiv: dict[str, TechniqueProposal] = {}
    for entry in entries:
        match = _ABS_ID_RE.search(entry.get("id") or "")
        title = (entry.get("title") or "").strip().replace("\n", " ")
        published = _published(entry)
        if not match or not title or published is None or published < since:
            continue
        arxiv_id = match.group(1)
        if arxiv_id in known_arxiv or arxiv_id in by_arxiv:
            continue
        matched = match_keyword(title)
        if matched is None:
            continue
        suggested_id = project_slug(title)
        if suggested_id in known_ids:
            continue
        keyword, domain, category = matched
        by_arxiv[arxiv_id] = TechniqueProposal(
            suggested_id=suggested_id, name=title, arxiv_id=arxiv_id,
            published=published.date().isoformat(), upvotes=0,
            suggested_domain=domain, suggested_category=category,
            matched_keyword=keyword, discovered_via="arxiv-sweep",
        )
    return list(by_arxiv.values())[:limit]


def _published(entry: Any) -> datetime | None:
    raw = entry.get("published") or entry.get("updated")
    if not raw:
        return None
    try:
        parsed = date_parser.parse(raw)
    except (ValueError, OverflowError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
