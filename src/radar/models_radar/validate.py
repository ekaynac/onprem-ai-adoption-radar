"""Blocking validation + advisories for model-catalog seeds.

A seed that fails validation is quarantined: excluded from scoring, rings,
and promotion, and surfaced as a warning instead. Prevents a mis-scraped
entry (664,944-param "35B") from ever ranking again.
"""

from __future__ import annotations

from radar.discovery.model_promotion import plausible_params
from radar.models_radar.benchmarks import CANONICAL_BENCHMARKS
from radar.models_radar.entities import ModelEntry, ModelSeed


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
    for benchmark in seed.benchmarks:
        if benchmark.name not in CANONICAL_BENCHMARKS:
            problems.append(
                f"{seed.id}: unknown benchmark key {benchmark.name!r} — "
                f"use a canonical key from models_radar.benchmarks"
            )
        if 0 < benchmark.score <= 1:
            problems.append(
                f"{seed.id}: benchmark {benchmark.name} score "
                f"{benchmark.score} looks fractional — transcribe on the "
                f"0-100 scale"
            )
        elif benchmark.score <= 0 or benchmark.score > 100:
            problems.append(
                f"{seed.id}: benchmark {benchmark.name} score "
                f"{benchmark.score} outside (0, 100]"
            )
    return problems


def seed_advisories(seed: ModelSeed) -> list[str]:
    """Non-blocking data-quality nudges (surfaced, never quarantined)."""
    advisories: list[str] = []
    if not seed.hf_repo:
        advisories.append(
            f"{seed.id}: no hf_repo — Hugging Face link missing from model surfaces"
        )
    return advisories


_BIG_MODEL_PARAMS = 70_000_000_000  # ≥70B with no architecture ⇒ D-phase answers wrong


def validate_entry(entry: ModelEntry) -> list[str]:
    """Blocking post-assembly problems; quarantined from scoring like bad seeds."""
    from radar.models_radar.memory import minimum_viable_quant

    problems: list[str] = []
    if entry.params_total is not None:
        mv = minimum_viable_quant(entry.quants)
        memory = mv.est_memory_gb_4k if mv else None
        if memory is None or memory <= 0:
            problems.append(
                f"{entry.id}: params known but minimum viable memory computed "
                f"as {memory} — spec data implausible"
            )
    return problems


def entry_advisories(entry: ModelEntry) -> list[str]:
    """Warn-only data-quality gaps on assembled entries."""
    advisories: list[str] = []
    if (
        entry.params_total is not None
        and entry.params_total >= _BIG_MODEL_PARAMS
        and entry.architecture is None
    ):
        advisories.append(
            f"{entry.id}: ≥70B model with no architecture data — "
            "capacity answers will be wrong"
        )
    for field in ("params_total", "context_length"):
        if getattr(entry, field) is not None and field not in entry.provenance:
            advisories.append(f"{entry.id}: {field} has no provenance")
    return advisories
