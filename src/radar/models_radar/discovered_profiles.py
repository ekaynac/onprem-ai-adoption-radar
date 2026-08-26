"""Bridge discovered intelligence releases into the advisor's candidate pool.

The discovery pipeline (HF sweep → qualification) already knows about
Laguna 2.1, Qwen3.6, DeepSeek V4 Flash, gpt-oss-120b and friends — with
params, context, license, and hf_repo claims. The curated seed does not
need a human to hand-enter them for the advisor to see them: this module
projects repository releases into advisor-compatible profile dicts.

Ring mapping is conservative — lifecycle is trust, not quality:
- detected  → watch (seen in the wild, unverified)
- verified  → pilot (architecture/claims verified against upstream)
- qualified/recommended → adopt (deployment-ready per policy)

Quants: NVFP4/FP8-suffixed releases synthesize a quant entry so the
capacity engine can size them; releases without total params are skipped
(nothing to size), and releases without sizing data surface with
fit=unknown plus an explicit assumption instead of being dropped.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from radar.intelligence.bootstrap import build_intelligence_repository


logger = logging.getLogger(__name__)

_LIFECYCLE_RING = {
    "detected": "watch",
    "verified": "pilot",
    "qualified": "adopt",
    "recommended": "adopt",
}

# ModelCategory values → the advisor's Modality enum. Categories without a
# faithful single-modality mapping land on multimodal/text per their nature.
_CATEGORY_MODALITY = {
    "text_reasoning": "text",
    "multimodal": "multimodal",
    "embedding_reranking": "text",
    "speech_audio": "audio",
    "image_video": "vision",
    "vision_document": "vision",
}

# Name-suffix → bits-per-weight heuristics for synthesized quants.
_SUFFIX_QUANTS = (
    ("nvfp4", ("NVFP4", 4.0)),
    ("-fp8", ("FP8", 8.0)),
    ("fp8-", ("FP8", 8.0)),
    ("-int4", ("INT4", 4.0)),
    ("-q4", ("Q4", 4.5)),
)


def _synth_quant(release_name: str) -> dict[str, Any] | None:
    lowered = release_name.lower()
    for suffix, (fmt, bpw) in _SUFFIX_QUANTS:
        if suffix in lowered:
            return {"format": fmt, "bits_per_weight": bpw, "source": "name-suffix"}
    return None


def build_discovered_profiles(root: Path) -> dict[str, dict[str, Any]]:
    """Project intelligence-repository releases into advisor profiles."""
    try:
        _database, repo = build_intelligence_repository(root)
    except Exception as exc:
        logger.warning(
            "Intelligence repository unavailable (%s); advisor falls back "
            "to curated seed only",
            exc,
        )
        return {}

    releases = repo.list_all_releases()
    release_ids = [release.id for release in releases]
    claim_map = repo.latest_claim_values(
        release_ids,
        {
            "hf_repo", "params_total", "params_active", "context_length",
            "license", "num_layers", "hidden_size",
        },
    )

    def _string_claim(value: Any) -> str | None:
        # HF license metadata arrives as str or list-of-tags depending on
        # the repo; the advisor contract needs one string or nothing.
        if isinstance(value, str):
            return value
        if isinstance(value, list) and value:
            return ", ".join(str(item) for item in value)
        return None

    profiles: dict[str, dict[str, Any]] = {}
    skipped = 0
    for release in releases:
        claims = claim_map.get(release.id) or {}
        params_total = claims.get("params_total")
        if not isinstance(params_total, int | float):
            # Without total params the capacity engine cannot size anything.
            continue
        short_id = release.id.removeprefix("release:legacy:")
        category_value = str(getattr(release.category, "value", "") or "text_reasoning")
        modality = _CATEGORY_MODALITY.get(category_value, "text")
        profiles[short_id] = {
            "id": short_id,
            "name": release.name,
            "family": release.family_id.removeprefix("family:") or release.name,
            "modality": modality,
            "ring": _LIFECYCLE_RING.get(str(release.lifecycle.value), "watch"),
            # Discovered entries carry no curated composite score; a neutral
            # maturity keeps their composite honest relative to seeded models.
            "score": 3.2,
            "license": _string_claim(claims.get("license")),
            "params_total": int(params_total),
            "params_active": (
                int(claims["params_active"])
                if isinstance(claims.get("params_active"), int | float)
                else None
            ),
            "num_layers": (
                claims["num_layers"]
                if isinstance(claims.get("num_layers"), int)
                else None
            ),
            "hidden_size": (
                claims["hidden_size"]
                if isinstance(claims.get("hidden_size"), int)
                else None
            ),
            "context_length": (
                int(claims["context_length"])
                if isinstance(claims.get("context_length"), int | float)
                else None
            ),
            "quants": (
                [quant] if (quant := _synth_quant(release.name)) else []
            ),
            "benchmark_aggregates": [],
            "discovered": True,
            "lifecycle": str(release.lifecycle.value),
            "source_url": (
                f"https://huggingface.co/{claims['hf_repo']}"
                if claims.get("hf_repo")
                else None
            ),
        }

    # Self-healing boundary: a profile that fails ModelEntry validation
    # (claim shape drift) is dropped with a warning, never allowed to kill
    # the export pipeline.
    from radar.models_radar.entities import ModelEntry

    validated: dict[str, dict[str, Any]] = {}
    for key, profile in profiles.items():
        try:
            ModelEntry.model_validate(profile)
        except Exception as exc:
            skipped += 1
            logger.warning(
                "Discovered profile %s failed validation and was skipped: %s",
                key,
                str(exc).splitlines()[0] if exc else exc,
            )
            continue
        validated[key] = profile
    if skipped:
        logger.warning("Skipped %d invalid discovered profile(s)", skipped)
    return validated


def merge_profile_pools(
    seeded: dict[str, dict[str, Any]],
    discovered: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Curated seed wins on id collisions, but sparse card data is
    backfilled from the repository's verified claims (e.g. params_active,
    which sizing/throughput need and hand-curated cards often omit)."""
    merged = dict(seeded)
    backfill_fields = (
        "params_active", "params_total", "context_length",
        "num_layers", "hidden_size",
    )
    for key, discovered_profile in discovered.items():
        if key not in merged:
            merged[key] = discovered_profile
            continue
        target = merged[key]
        for field in backfill_fields:
            if not target.get(field) and discovered_profile.get(field):
                target[field] = discovered_profile[field]
        if not target.get("source_url") and discovered_profile.get("source_url"):
            target["source_url"] = discovered_profile["source_url"]
    return merged
