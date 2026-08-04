from __future__ import annotations

from datetime import UTC, datetime

from radar.storage.benchmark_observations_log import (
    BenchmarkObservation,
    append_benchmark_observations,
    load_benchmark_observations,
)


def make_observation(**overrides) -> BenchmarkObservation:
    values = {
        "model_id": "qwen3-32b",
        "hf_repo": "Qwen/Qwen3-32B",
        "benchmark": "mmlu-pro",
        "score": 63.2,
        "source_id": "open-llm-leaderboard",
        "source_url": "https://huggingface.co/datasets/open-llm-leaderboard/contents",
        "observed_at": datetime(2026, 8, 4, 8, tzinfo=UTC),
    }
    values.update(overrides)
    return BenchmarkObservation.model_validate(values)


def test_round_trip(tmp_path) -> None:
    path = tmp_path / "benchmark-observations.jsonl"
    rows = [make_observation(), make_observation(benchmark="ifeval", score=81.0)]

    append_benchmark_observations(path, rows)
    append_benchmark_observations(path, [])  # no-op

    assert load_benchmark_observations(path) == rows


def test_missing_file_loads_empty(tmp_path) -> None:
    assert load_benchmark_observations(tmp_path / "absent.jsonl") == []


def test_corrupt_line_is_skipped_not_fatal(tmp_path) -> None:
    path = tmp_path / "benchmark-observations.jsonl"
    append_benchmark_observations(path, [make_observation()])
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    append_benchmark_observations(path, [make_observation(score=64.0)])

    loaded = load_benchmark_observations(path)

    assert [item.score for item in loaded] == [63.2, 64.0]


def test_naive_observed_at_is_restamped_utc() -> None:
    observation = make_observation(observed_at=datetime(2026, 8, 4, 8))
    assert observation.observed_at.tzinfo is UTC
