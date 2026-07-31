"""Sweep untracked HF-trending models into candidate observations.

Reuses discover_trending_models (which already excludes seeded/tracked repos and
degrades to [] on network failure) — we just stamp each result with observed_at
so velocity can emerge across daily runs.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from radar.discovery.hf_trending_models import discover_trending_models
from radar.discovery.model_proposals import ModelProposal
from radar.models_radar.entities import ModelSeed
from radar.storage.model_candidate_log import ModelCandidateObservation


MODEL_PIPELINE_TAGS = (
    "text-generation",
    "image-text-to-text",
    "feature-extraction",
    "sentence-similarity",
    "automatic-speech-recognition",
    "text-to-speech",
    "text-to-image",
    "text-to-video",
    "image-to-text",
)
RECENT_LANE_LIMIT = 150
TRENDING_LANE_LIMIT = 100


async def sweep_model_candidates(
    seeds: list[ModelSeed],
    client: Any,
    now: datetime,
    headers: dict[str, str] | None = None,
    health: dict[str, int] | None = None,
) -> list[ModelCandidateObservation]:
    # A trending-only, text-only query misses exactly the releases for which
    # freshness matters most: new official artifacts with low download counts
    # and non-text modalities. Query both discovery shapes across all supported
    # model categories, then deduplicate by stable HF repository id.
    queries = [
        (pipeline_tag, sort, min_downloads, query_limit)
        for pipeline_tag in MODEL_PIPELINE_TAGS
        for sort, min_downloads, query_limit in (
            ("lastModified", 0, 100),
            ("trendingScore", 10_000, 50),
        )
    ]
    batches = await asyncio.gather(
        *(
            discover_trending_models(
                seeds,
                client,
                min_downloads=min_downloads,
                limit=query_limit,
                pipeline_tag=pipeline_tag,
                sort=sort,
                headers=headers,
                health=health,
            )
            for pipeline_tag, sort, min_downloads, query_limit in queries
        )
    )
    recent: list[ModelProposal] = []
    trending: list[ModelProposal] = []
    for (_pipeline_tag, sort, _minimum, _query_limit), proposals in zip(
        queries,
        batches,
        strict=True,
    ):
        (recent if sort == "lastModified" else trending).extend(proposals)

    def best_by_repo(proposals: list[ModelProposal]) -> list[ModelProposal]:
        selected: dict[
            str,
            tuple[tuple[bool, str, bool, int, int], ModelProposal],
        ] = {}
        for proposal in proposals:
            key = proposal.hf_repo.casefold()
            current = selected.get(key)
            quality = (
                bool(proposal.last_modified),
                proposal.last_modified or "",
                bool(proposal.created_at),
                proposal.downloads,
                proposal.likes,
            )
            if current is None or quality > current[0]:
                selected[key] = (quality, proposal)
        return [item[1] for item in selected.values()]

    recent = sorted(
        best_by_repo(recent),
        key=lambda proposal: (
            proposal.last_modified or proposal.created_at or "",
            proposal.downloads,
        ),
        reverse=True,
    )[:RECENT_LANE_LIMIT]
    trending = sorted(
        best_by_repo(trending),
        key=lambda proposal: (proposal.downloads, proposal.likes),
        reverse=True,
    )[:TRENDING_LANE_LIMIT]
    by_repo = {
        proposal.hf_repo.casefold(): proposal
        for proposal in [*trending, *recent]
    }
    proposals = sorted(
        by_repo.values(),
        key=lambda proposal: (
            proposal.last_modified or "",
            proposal.downloads,
            proposal.likes,
        ),
        reverse=True,
    )
    return [
        ModelCandidateObservation(
            hf_repo=p.hf_repo, name=p.name, family=p.family,
            downloads=p.downloads, likes=p.likes,
            pipeline_tag=p.pipeline_tag,
            created_at=p.created_at,
            last_modified=p.last_modified,
            observed_at=now,
        )
        for p in proposals
    ]
