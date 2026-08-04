"""Canonical benchmark registry, score normalization, and triangulation.

Benchmark scores arrive from leaderboards (scraped observations) and from
model cards (curated seed values). Triangulation only ever compares
scores under the SAME canonical key: methodologies differ between
leaderboards and cards (e.g. the Open LLM Leaderboard publishes
baseline-normalized GPQA while model cards report raw GPQA-Diamond), so
those are deliberately distinct keys. Never add a key that mixes
methodologies, and never fuzzy-match names into keys.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from statistics import median
from typing import Any


CANONICAL_BENCHMARKS: dict[str, str] = {
    "ifeval": "IFEval",
    "bbh": "BBH",
    "math-l5": "MATH Level 5",
    "gpqa": "GPQA (OLLB-normalized)",
    "gpqa-diamond": "GPQA-Diamond",
    "musr": "MUSR",
    "mmlu-pro": "MMLU-Pro",
    "mmlu": "MMLU",
    "ollb-average": "Open LLM Leaderboard average",
    "aider-polyglot": "Aider polyglot (pass rate)",
    "livebench-coding": "LiveBench coding",
    "livebench-code-completion": "LiveBench code completion",
    "livebench-math-amps": "LiveBench AMPS hard",
    "humaneval": "HumanEval",
    "swe-bench-verified": "SWE-bench Verified",
    "aime-2025": "AIME 2025",
    "livecodebench": "LiveCodeBench",
}

MODEL_CARD_SOURCE_ID = "model-card"
DEFAULT_TRIANGULATION_GAP_POINTS = 5.0


def normalize_score(benchmark: str, raw: float) -> float:
    """Return the score on the canonical 0-100 scale.

    Published scores for every canonical benchmark are percentages; no
    legitimate result on these suites is <= 1 point, so a value in
    (0, 1] is treated as a fraction and scaled. Values of 0 stay 0.
    """
    del benchmark  # every current key shares the 0-100 convention
    if 0 < raw <= 1.0:
        return round(raw * 100, 2)
    return round(raw, 2)


def build_benchmark_aggregates(
    seeds_by_id: Mapping[str, Any],
    observations: Iterable[Any],
    *,
    gap_points: float = DEFAULT_TRIANGULATION_GAP_POINTS,
) -> dict[str, list[dict[str, Any]]]:
    """Reduce observations + seed card values into per-model aggregates.

    - ``scores``: latest row per source for each (model, benchmark),
      with the seed's card values merged as the self-reported channel.
    - ``consensus``: median of independent sources, falling back to the
      self-reported value when no independent source exists.
    - ``self_reported_gap``: self minus median(independent); ``flagged``
      when its magnitude exceeds ``gap_points``.
    - ``percentile``: rank of consensus among tracked models sharing the
      key (null when fewer than two models have it).
    """
    latest: dict[tuple[str, str, str], Any] = {}
    for observation in observations:
        key = (
            observation.model_id,
            observation.benchmark,
            observation.source_id,
        )
        current = latest.get(key)
        if current is None or observation.observed_at > current.observed_at:
            latest[key] = observation

    per_model_benchmark: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for (model_id, benchmark, _source), observation in latest.items():
        per_model_benchmark.setdefault((model_id, benchmark), []).append(
            {
                "source_id": observation.source_id,
                "score": normalize_score(benchmark, observation.score),
                "source_url": observation.source_url,
                "observed_at": observation.observed_at.isoformat(),
                "self_reported": bool(observation.self_reported),
            }
        )

    for model_id, seed in seeds_by_id.items():
        for card_score in getattr(seed, "benchmarks", []) or []:
            benchmark = card_score.name
            per_model_benchmark.setdefault((model_id, benchmark), []).append(
                {
                    "source_id": MODEL_CARD_SOURCE_ID,
                    "score": normalize_score(benchmark, card_score.score),
                    "source_url": card_score.source_url,
                    "observed_at": None,
                    "self_reported": True,
                }
            )

    aggregates_by_model: dict[str, list[dict[str, Any]]] = {}
    consensus_by_benchmark: dict[str, list[tuple[str, float]]] = {}
    for (model_id, benchmark), scores in per_model_benchmark.items():
        scores.sort(key=lambda item: (item["self_reported"], item["source_id"]))
        independent = [
            item["score"] for item in scores if not item["self_reported"]
        ]
        self_reported = [
            item["score"] for item in scores if item["self_reported"]
        ]
        consensus = (
            median(independent)
            if independent
            else (self_reported[0] if self_reported else None)
        )
        gap = (
            round(self_reported[0] - median(independent), 2)
            if independent and self_reported
            else None
        )
        all_scores = [item["score"] for item in scores]
        aggregate = {
            "benchmark": benchmark,
            "label": CANONICAL_BENCHMARKS.get(benchmark, benchmark),
            "scores": scores,
            "consensus": consensus,
            "spread": (
                round(max(all_scores) - min(all_scores), 2)
                if len(all_scores) > 1
                else None
            ),
            "self_reported_gap": gap,
            "flagged": gap is not None and abs(gap) > gap_points,
            "percentile": None,
            "sample_size": 0,
        }
        aggregates_by_model.setdefault(model_id, []).append(aggregate)
        if consensus is not None:
            consensus_by_benchmark.setdefault(benchmark, []).append(
                (model_id, consensus)
            )

    for benchmark, entries in consensus_by_benchmark.items():
        sample_size = len(entries)
        values = sorted(value for _model, value in entries)
        for model_id, value in entries:
            aggregate = next(
                item
                for item in aggregates_by_model[model_id]
                if item["benchmark"] == benchmark
            )
            aggregate["sample_size"] = sample_size
            if sample_size >= 2:
                below = sum(1 for other in values if other < value)
                aggregate["percentile"] = round(
                    below / (sample_size - 1) * 100
                )

    for aggregates in aggregates_by_model.values():
        aggregates.sort(key=lambda item: item["benchmark"])
    return aggregates_by_model
