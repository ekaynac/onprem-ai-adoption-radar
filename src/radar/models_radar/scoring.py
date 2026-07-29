"""Deterministic adoption scoring + ring for local models.

Model-specific dimensions (1-5), no LLM. Mirrors the tool radar's
ring_from_score gate style but over model criteria.
"""

from __future__ import annotations

from radar.models import Ring
from radar.models_radar.entities import HardwareTier, ModelEntry, ModelScore, Openness
from radar.models_radar.memory import minimum_viable_quant


_OPENNESS_SCORE = {
    Openness.OPEN_PERMISSIVE: 5,
    Openness.OPEN_RESTRICTED: 3,
    Openness.GATED: 2,
    Openness.CLOSED: 1,
}
_TIER_SCORE = {
    HardwareTier.LAPTOP: 5,
    HardwareTier.APPLE_HIGH_RAM: 4,
    HardwareTier.SINGLE_GPU: 3,
    HardwareTier.WORKSTATION: 2,
    HardwareTier.SINGLE_GPU_DC: 2,
    HardwareTier.SINGLE_NODE: 1,
    HardwareTier.MULTI_NODE: 1,
    HardwareTier.DATACENTER: 1,  # legacy-persisted entries only; homelab default penalty
    HardwareTier.UNKNOWN: 2,
}


def _capability(entry: ModelEntry) -> int:
    """Bigger models score higher capability (by total params)."""
    p = entry.params_total or 0
    if p >= 100_000_000_000:
        return 5
    if p >= 30_000_000_000:
        return 4
    if p >= 12_000_000_000:
        return 3
    if p >= 3_000_000_000:
        return 2
    return 1


def _ecosystem(entry: ModelEntry) -> int:
    """More resident quant formats + Ollama presence → better support."""
    formats = {q.format for q in entry.quants}
    score = 1 + min(3, len(formats))
    if entry.ollama_name:
        score = min(5, score + 1)
    return min(5, score)


class ModelProfileError(ValueError):
    """Raised for an unknown model-scoring profile."""


MODEL_PROFILES: dict[str, dict[HardwareTier, int]] = {
    "default": _TIER_SCORE,
    # Datacenter lens: single-node/multi-node deployability is the point,
    # not a penalty. Laptop-class models still score fine on capability.
    "datacenter-first": {
        HardwareTier.LAPTOP: 2, HardwareTier.APPLE_HIGH_RAM: 2,
        HardwareTier.SINGLE_GPU: 3, HardwareTier.WORKSTATION: 4,
        HardwareTier.SINGLE_GPU_DC: 5, HardwareTier.SINGLE_NODE: 5,
        HardwareTier.MULTI_NODE: 4, HardwareTier.DATACENTER: 4,
        HardwareTier.UNKNOWN: 2,
    },
}


def score_model(entry: ModelEntry, profile: str = "default") -> ModelScore:
    tier_scores = MODEL_PROFILES.get(profile)
    if tier_scores is None:
        available = ", ".join(sorted(MODEL_PROFILES))
        raise ModelProfileError(
            f"Unknown model-scoring profile {profile!r}; available: {available}"
        )
    openness = _OPENNESS_SCORE.get(entry.openness, 2) if entry.openness else 2
    mv = minimum_viable_quant(entry.quants)
    runnability = tier_scores[entry.hardware_tier] if mv else 2
    capability = _capability(entry)
    ecosystem = _ecosystem(entry)
    average = round((openness + runnability + capability + ecosystem) / 4, 2)
    return ModelScore(
        openness=openness, local_runnability=runnability,
        capability_tier=capability, ecosystem_support=ecosystem, average=average,
    )


def model_ring(score: ModelScore) -> Ring:
    """Absolute ring gate over the model score average + openness floor."""
    if score.average < 2.0 or score.openness <= 1:
        return Ring.AVOID
    if score.average >= 4.0 and score.openness >= 3:
        return Ring.ADOPT
    if score.average >= 3.0:
        return Ring.PILOT
    return Ring.WATCH


def rescore_entries(entries: list[ModelEntry], profile: str) -> list[ModelEntry]:
    """Recompute score/breakdown/ring per entry under an alternate scoring lens.

    A view only — the input entries (and any persisted rings) are never
    mutated; frozen `ModelEntry` copies are returned instead. `"default"` is
    the identity transform: it returns the input list unchanged rather than
    recomputing scores that are already current.
    """
    if profile == "default":
        return entries
    rescored: list[ModelEntry] = []
    for entry in entries:
        breakdown = score_model(entry, profile=profile)
        ring = model_ring(breakdown)
        rescored.append(entry.model_copy(update={
            "score": breakdown.average, "score_breakdown": breakdown, "ring": ring,
        }))
    return rescored
