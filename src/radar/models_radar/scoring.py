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
    HardwareTier.DATACENTER: 1,
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


def score_model(entry: ModelEntry) -> ModelScore:
    openness = _OPENNESS_SCORE.get(entry.openness, 2) if entry.openness else 2
    mv = minimum_viable_quant(entry.quants)
    runnability = _TIER_SCORE[entry.hardware_tier] if mv else 2
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
