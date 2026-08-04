from __future__ import annotations

from datetime import UTC, datetime

from radar.models_radar.benchmarks import (
    CANONICAL_BENCHMARKS,
    build_benchmark_aggregates,
    normalize_score,
)
from radar.models_radar.entities import BenchmarkScore, ModelSeed
from radar.storage.benchmark_observations_log import BenchmarkObservation


NOW = datetime(2026, 8, 4, 8, tzinfo=UTC)


def obs(**overrides) -> BenchmarkObservation:
    values = {
        "model_id": "qwen3-32b",
        "benchmark": "mmlu-pro",
        "score": 63.2,
        "source_id": "open-llm-leaderboard",
        "source_url": "https://ollb.example/row",
        "observed_at": NOW,
    }
    values.update(overrides)
    return BenchmarkObservation.model_validate(values)


def seed(model_id: str, benchmarks: list[BenchmarkScore]) -> ModelSeed:
    return ModelSeed(
        id=model_id,
        name=model_id,
        family="Test",
        benchmarks=benchmarks,
    )


def test_normalize_score_scales_fractions_only() -> None:
    assert normalize_score("mmlu-pro", 0.81) == 81.0
    assert normalize_score("mmlu-pro", 63.2) == 63.2
    assert normalize_score("mmlu-pro", 1.0) == 100.0
    assert normalize_score("mmlu-pro", 0) == 0


def test_latest_per_source_wins_and_duplicates_collapse() -> None:
    aggregates = build_benchmark_aggregates(
        {},
        [
            obs(score=60.0, observed_at=datetime(2026, 8, 1, tzinfo=UTC)),
            obs(score=63.2, observed_at=NOW),
        ],
    )

    scores = aggregates["qwen3-32b"][0]["scores"]
    assert len(scores) == 1
    assert scores[0]["score"] == 63.2


def test_triangulation_gap_flags_both_directions() -> None:
    seeds = {
        "qwen3-32b": seed(
            "qwen3-32b",
            [
                BenchmarkScore(
                    name="mmlu-pro",
                    score=70.0,
                    source_url="https://card.example",
                )
            ],
        )
    }
    flagged_up = build_benchmark_aggregates(seeds, [obs(score=63.2)])
    row = flagged_up["qwen3-32b"][0]
    assert row["self_reported_gap"] == 6.8
    assert row["flagged"] is True
    assert row["consensus"] == 63.2  # independent median wins

    within = build_benchmark_aggregates(
        seeds, [obs(score=66.0)], gap_points=5.0
    )
    assert within["qwen3-32b"][0]["flagged"] is False

    flagged_down = build_benchmark_aggregates(
        {
            "qwen3-32b": seed(
                "qwen3-32b",
                [
                    BenchmarkScore(
                        name="mmlu-pro",
                        score=55.0,
                        source_url="https://card.example",
                    )
                ],
            )
        },
        [obs(score=63.2)],
    )
    assert flagged_down["qwen3-32b"][0]["self_reported_gap"] == -8.2
    assert flagged_down["qwen3-32b"][0]["flagged"] is True


def test_self_reported_only_falls_back_without_flag() -> None:
    aggregates = build_benchmark_aggregates(
        {
            "qwen3-32b": seed(
                "qwen3-32b",
                [
                    BenchmarkScore(
                        name="gpqa-diamond",
                        score=0.66,  # fractional card value normalized
                        source_url="https://card.example",
                    )
                ],
            )
        },
        [],
    )

    row = aggregates["qwen3-32b"][0]
    assert row["consensus"] == 66.0
    assert row["self_reported_gap"] is None
    assert row["flagged"] is False
    assert row["scores"][0]["self_reported"] is True


def test_spread_and_independent_only_gap() -> None:
    aggregates = build_benchmark_aggregates(
        {},
        [
            obs(score=60.0),
            obs(score=70.0, source_id="livebench", source_url="https://lb.example"),
        ],
    )

    row = aggregates["qwen3-32b"][0]
    assert row["spread"] == 10.0
    assert row["consensus"] == 65.0
    assert row["self_reported_gap"] is None


def test_percentiles_across_tracked_models() -> None:
    aggregates = build_benchmark_aggregates(
        {},
        [
            obs(model_id="model-a", score=50.0),
            obs(model_id="model-b", score=60.0),
            obs(model_id="model-c", score=70.0),
            # Single-model benchmark: percentile stays null.
            obs(model_id="model-a", benchmark="ifeval", score=80.0),
        ],
    )

    by_model = {
        model_id: {row["benchmark"]: row for row in rows}
        for model_id, rows in aggregates.items()
    }
    assert by_model["model-a"]["mmlu-pro"]["percentile"] == 0
    assert by_model["model-b"]["mmlu-pro"]["percentile"] == 50
    assert by_model["model-c"]["mmlu-pro"]["percentile"] == 100
    assert by_model["model-a"]["mmlu-pro"]["sample_size"] == 3
    assert by_model["model-a"]["ifeval"]["percentile"] is None
    assert by_model["model-a"]["ifeval"]["sample_size"] == 1


def test_labels_come_from_the_registry() -> None:
    aggregates = build_benchmark_aggregates({}, [obs()])
    assert aggregates["qwen3-32b"][0]["label"] == CANONICAL_BENCHMARKS["mmlu-pro"]
