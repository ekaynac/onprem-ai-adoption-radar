"""Discover trending local-runnable models from the Hugging Face Hub.

Queries the HF models list endpoint, drops models already in the seed and those
below a download floor, and returns proposals ranked by downloads. Best-effort:
a network failure degrades to no proposals. Results are only ever written to the
review file (see model_proposals.py) — never auto-added to the seed.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from radar.discovery.model_proposals import ModelProposal
from radar.models_radar.entities import ModelSeed
from radar.web.slugs import project_slug


logger = logging.getLogger(__name__)

HF_MODELS_URL = "https://huggingface.co/api/models"
_MODALITY_BY_TAG = {
    "text-generation": "text",
    "image-text-to-text": "multimodal",
    "automatic-speech-recognition": "audio",
    "text-to-image": "vision",
}


class _AsyncClient(Protocol):
    async def get(self, url: str, **kwargs: Any) -> Any: ...


async def fetch_trending_models(
    client: _AsyncClient,
    limit: int = 50,
    pipeline_tag: str = "text-generation",
    sort: str = "trendingScore",
    headers: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """HF models list (best-effort → [])."""
    try:
        response = await client.get(
            HF_MODELS_URL,
            params={"sort": sort, "direction": -1, "limit": limit,
                    "pipeline_tag": pipeline_tag},
            headers=headers or {},
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else []
    except Exception as exc:
        logger.warning("HF trending-models fetch failed: %s", exc)
        return []


async def discover_trending_models(
    seeds: list[ModelSeed],
    client: _AsyncClient,
    min_downloads: int = 10000,
    limit: int = 50,
    headers: dict[str, str] | None = None,
) -> list[ModelProposal]:
    """Trending models not already seeded, above the download floor, ranked by downloads."""
    seeded = {(s.hf_repo or "").lower() for s in seeds if s.hf_repo}
    items = await fetch_trending_models(client, limit=limit, headers=headers)
    proposals: list[ModelProposal] = []
    for item in items:
        repo = item.get("id") or ""
        if not repo or repo.lower() in seeded:
            continue
        downloads = int(item.get("downloads") or 0)
        if downloads < min_downloads:
            continue
        likes = int(item.get("likes") or 0)
        name = repo.split("/")[-1]
        family = repo.split("/")[0] if "/" in repo else name
        modality = _MODALITY_BY_TAG.get(item.get("pipeline_tag") or "", "text")
        proposals.append(ModelProposal(
            model_id=name, name=name, family=family, hf_repo=repo,
            downloads=downloads, likes=likes, modality=modality,
            reason=f"trending: {downloads} downloads, {likes} likes",
            suggested_id=f"hf-{project_slug(name)}",
        ))
    return sorted(proposals, key=lambda p: p.downloads, reverse=True)[:limit]
