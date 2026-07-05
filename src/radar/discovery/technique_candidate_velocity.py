"""Citations/day enrichment for discovery proposals.

A deterministic single-observation velocity proxy: citations ÷ days since
publication. Real spike detection needs two observations over time of papers
we do not track; this proxy ranks fresh-but-already-cited papers first, which
is the actionable part of "citation-velocity spikes" for a human reviewer.
Best-effort: enrichment failure returns the proposals unchanged.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from radar.discovery.technique_proposals import TechniqueProposal
from radar.research_radar.citations import fetch_citations


logger = logging.getLogger(__name__)


async def enrich_proposals_with_velocity(
    proposals: list[TechniqueProposal],
    client: Any,
    now: datetime,
    contact_email: str | None = None,
) -> list[TechniqueProposal]:
    if not proposals:
        return []
    try:
        records = await fetch_citations(
            [p.arxiv_id for p in proposals], client, contact_email
        )
    except Exception as exc:  # fetch_citations already degrades; belt and braces
        logger.warning("Velocity enrichment failed: %s", exc)
        return proposals
    if not records:
        return proposals
    enriched: list[TechniqueProposal] = []
    for proposal in proposals:
        record = records.get(proposal.arxiv_id)
        if record is None:
            enriched.append(proposal)
            continue
        enriched.append(proposal.model_copy(update={
            "citation_count": record.citation_count,
            "citations_per_day": _velocity(record.citation_count, proposal.published, now),
        }))
    return enriched


def rank_proposals(proposals: list[TechniqueProposal]) -> list[TechniqueProposal]:
    """Velocity desc (unknown treated as zero signal), then upvotes desc, then arxiv_id."""
    return sorted(proposals, key=lambda p: (
        -(p.citations_per_day or 0.0),
        -p.upvotes,
        p.arxiv_id,
    ))


def _velocity(count: int, published: str | None, now: datetime) -> float | None:
    if not published:
        return None
    normalized = f"{published}-01" if len(published) == 7 else published
    try:
        start = datetime.fromisoformat(normalized).replace(tzinfo=UTC)
    except ValueError:
        return None
    days = max((now - start).days, 1)
    return round(count / days, 2)
