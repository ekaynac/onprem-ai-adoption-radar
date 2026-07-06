"""Sweep untracked HF/arXiv paper candidates into observations.

Mirrors `research discover`'s gather+dedup+enrich (HF wins duplicates), then
stamps each with observed_at so upvote velocity can emerge across daily runs.
Best-effort: any fetch failure degrades to [] (the fetchers already degrade
internally; this outer guard honors the contract even if one raises).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from radar.discovery import (
    arxiv_technique_candidates,
    hf_technique_candidates,
    technique_candidate_velocity,
)
from radar.research_radar.entities import TechniqueSeed
from radar.storage.technique_candidate_log import TechniqueCandidateObservation


logger = logging.getLogger(__name__)


async def sweep_technique_candidates(
    seeds: list[TechniqueSeed],
    client: Any,
    now: datetime,
    *,
    days: int = 7,
    min_upvotes: int = 10,
    limit: int = 20,
    contact_email: str | None = None,
) -> list[TechniqueCandidateObservation]:
    try:
        gathered = await hf_technique_candidates.discover_technique_candidates(
            seeds, client, min_upvotes=min_upvotes, limit=limit)
        arxiv_found = await arxiv_technique_candidates.discover_arxiv_candidates(
            seeds, client, since=now - timedelta(days=days), limit=limit)
        seen = {p.arxiv_id for p in gathered}  # HF entries win duplicates
        gathered = [*gathered, *(p for p in arxiv_found if p.arxiv_id not in seen)]
        enriched = await technique_candidate_velocity.enrich_proposals_with_velocity(
            gathered, client, now=now, contact_email=contact_email)
    except Exception as exc:
        logger.warning("Paper-candidate sweep failed: %s", exc)
        return []
    return [
        TechniqueCandidateObservation(
            arxiv_id=p.arxiv_id, name=p.name, upvotes=p.upvotes,
            citation_count=p.citation_count, published=p.published,
            suggested_domain=p.suggested_domain.value,
            suggested_category=p.suggested_category.value, observed_at=now,
        )
        for p in enriched
    ]
