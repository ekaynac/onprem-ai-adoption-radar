"""Sweep untracked HF-trending models into candidate observations.

Reuses discover_trending_models (which already excludes seeded/tracked repos and
degrades to [] on network failure) — we just stamp each result with observed_at
so velocity can emerge across daily runs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from radar.discovery.hf_trending_models import discover_trending_models
from radar.models_radar.entities import ModelSeed
from radar.storage.model_candidate_log import ModelCandidateObservation


async def sweep_model_candidates(
    seeds: list[ModelSeed],
    client: Any,
    now: datetime,
    headers: dict[str, str] | None = None,
) -> list[ModelCandidateObservation]:
    proposals = await discover_trending_models(seeds, client, headers=headers)
    return [
        ModelCandidateObservation(
            hf_repo=p.hf_repo, name=p.name, family=p.family,
            downloads=p.downloads, likes=p.likes, observed_at=now,
        )
        for p in proposals
    ]
