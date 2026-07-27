"""Blocking validation + advisories for model-catalog seeds.

A seed that fails validation is quarantined: excluded from scoring, rings,
and promotion, and surfaced as a warning instead. Prevents a mis-scraped
entry (664,944-param "35B") from ever ranking again.
"""

from __future__ import annotations

from radar.discovery.model_promotion import plausible_params
from radar.models_radar.entities import ModelSeed


def validate_seed(seed: ModelSeed) -> list[str]:
    """Blocking problems; an empty list means the seed may be scored."""
    problems: list[str] = []
    if seed.params_total is not None:
        if seed.params_total <= 0:
            problems.append(f"{seed.id}: params_total must be positive")
        elif plausible_params(seed.name, seed.params_total) is None:
            problems.append(
                f"{seed.id}: implausible params_total {seed.params_total} "
                f"for name {seed.name!r}"
            )
    if (
        seed.params_active is not None
        and seed.params_total is not None
        and seed.params_active > seed.params_total
    ):
        problems.append(f"{seed.id}: params_active exceeds params_total")
    if seed.context_length is not None and seed.context_length <= 0:
        problems.append(f"{seed.id}: context_length must be positive")
    return problems


def seed_advisories(seed: ModelSeed) -> list[str]:
    """Non-blocking data-quality nudges (surfaced, never quarantined)."""
    advisories: list[str] = []
    if not seed.hf_repo:
        advisories.append(
            f"{seed.id}: no hf_repo — Hugging Face link missing from model surfaces"
        )
    return advisories
