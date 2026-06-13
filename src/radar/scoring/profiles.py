"""Scoring profiles: per-dimension weight presets over the 7-dimension score.

The default decision uses an equal-weighted average (the plain
``ScoreBreakdown.average``). A profile re-weights the dimensions before
calibration so an org can rank the same observed data through its own lens —
``security-first`` leans on security_posture, ``solo-dev`` on laptop
runnability and setup friction, and so on. The math stays deterministic.
"""

from __future__ import annotations

from radar.models import _SCORE_DIMENSIONS, DecisionCard, ScoreBreakdown
from radar.scoring.calibrate import calibrate_rings


DIMENSIONS = _SCORE_DIMENSIONS


def weighted_average(
    scores: ScoreBreakdown,
    weights: dict[str, float] | None,
) -> float:
    """Weighted mean of the dimensions; ``None`` returns the plain average.

    Unspecified dimensions default to weight 1.0. A profile whose weights sum
    to zero is meaningless and rejected.
    """
    if not weights:
        return scores.average

    total_weight = 0.0
    weighted_sum = 0.0
    for dimension in DIMENSIONS:
        weight = float(weights.get(dimension, 1.0))
        total_weight += weight
        weighted_sum += weight * getattr(scores, dimension)
    if total_weight <= 0:
        raise ValueError("Profile weights must sum to a positive number.")
    return round(weighted_sum / total_weight, 2)


class UnknownProfileError(ValueError):
    """Raised when a requested profile name is not configured."""


def resolve_weights(
    profiles: dict[str, dict[str, float]],
    name: str,
) -> dict[str, float]:
    """Look up a named profile's weights, or raise with the available names."""
    if name not in profiles:
        available = ", ".join(sorted(profiles)) or "(none configured)"
        raise UnknownProfileError(
            f"Unknown profile '{name}'. Available: {available}."
        )
    return profiles[name]


def reweight_cards(
    cards: list[DecisionCard],
    weights: dict[str, float] | None,
) -> list[DecisionCard]:
    """Re-rank stored cards through a profile lens without a re-scan.

    Recomputes each card's score and re-runs ring calibration from the stored
    per-dimension breakdowns. Cards without a breakdown (legacy/pinned) keep
    their stored ring and score. Never mutates the input.
    """
    if not weights:
        return cards

    # Pinned cards keep the human decision; legacy cards lack the breakdown.
    reweightable = [
        c for c in cards if c.score_breakdown is not None and not c.pinned
    ]
    if not reweightable:
        return cards

    breakdowns = {c.project: _require_breakdown(c) for c in reweightable}
    entries = [
        (
            weighted_average(breakdowns[c.project], weights),
            breakdowns[c.project].security_posture,
            breakdowns[c.project].on_prem_relevance,
        )
        for c in reweightable
    ]
    rings = calibrate_rings(entries)
    new_rings = dict(zip((c.project for c in reweightable), rings, strict=True))

    result: list[DecisionCard] = []
    for card in cards:
        if card.project not in new_rings:
            result.append(card)
            continue
        result.append(
            card.model_copy(
                update={
                    "ring": new_rings[card.project],
                    "score": weighted_average(breakdowns[card.project], weights),
                }
            )
        )
    return result


def _require_breakdown(card: DecisionCard) -> ScoreBreakdown:
    assert card.score_breakdown is not None  # guarded by the filter above
    return card.score_breakdown
