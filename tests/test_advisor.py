from __future__ import annotations

import pytest

from radar.models_radar.advisor import TASKS, build_answers


def profile(**overrides) -> dict:
    values = {
        "id": "qwen3-8b",
        "name": "Qwen3-8B",
        "family": "Qwen3",
        "modality": "text",
        "ring": "adopt",
        "score": 4.0,
        "license": "apache-2.0",
        "params_total": 8_000_000_000,
        "num_layers": 32,
        "hidden_size": 4096,
        "context_length": 131072,
        "quants": [
            {
                "format": "GGUF Q4_K_M",
                "bits_per_weight": 4.5,
                "source": "manual",
            }
        ],
        "benchmark_aggregates": [
            {
                "benchmark": "aider-polyglot",
                "label": "Aider polyglot (pass rate)",
                "consensus": 45.0,
                "spread": None,
                "self_reported_gap": None,
                "flagged": False,
                "percentile": 60,
                "sample_size": 5,
                "scores": [],
            }
        ],
    }
    values.update(overrides)
    return values


def test_ranks_candidates_with_six_cited_components() -> None:
    profiles = {
        "qwen3-8b": profile(),
        "small-no-bench": profile(
            id="small-no-bench",
            name="Small NoBench",
            ring="pilot",
            score=3.0,
            params_total=1_000_000_000,
            benchmark_aggregates=[],
        ),
    }

    answer = build_answers(profiles, "rtx-4090-24gb", "coding")

    assert answer["task_label"] == "Coding assistant"
    assert answer["cost"]["note"].startswith("Device-level")
    first = answer["candidates"][0]
    assert first["model_id"] == "qwen3-8b"
    assert first["fit"]["verdict"] in {"fits", "fits_tight", "fits_quantized"}
    assert first["task_capability"]["percentile"] == 60
    assert first["license"]["allowed"] is True
    assert any("Task capability p60" in reason for reason in first["reasons"])
    # The benchmark-less candidate ranks on its curated score, with the
    # assumption stated — never an invented percentile.
    second = answer["candidates"][1]
    assert second["task_capability"] is None
    assert any("No tracked benchmarks" in a for a in second["assumptions"])
    assert first["composite"] > second["composite"]


def test_policy_and_capacity_exclusions_are_visible() -> None:
    profiles = {
        "qwen3-8b": profile(),
        "gpl-model": profile(id="gpl-model", name="GPL Model", license="agpl-3.0"),
        "avoided": profile(id="avoided", name="Avoided", ring="avoid"),
        "huge": profile(
            id="huge",
            name="Huge 1T",
            params_total=1_000_000_000_000,
            quants=[
                {"format": "FP16", "bits_per_weight": 16.0, "source": "manual"}
            ],
        ),
        "short-context": profile(
            id="short-context", name="Shorty", context_length=8192
        ),
    }

    answer = build_answers(
        profiles,
        "a100-80gb",
        "coding",
        allowed_licenses=["apache-2.0", "mit"],
        min_context=32768,
    )

    assert [c["model_id"] for c in answer["candidates"]] == ["qwen3-8b"]
    reasons = {row["model_id"]: row["reason"] for row in answer["excluded"]}
    assert "not in policy" in reasons["gpl-model"]
    assert reasons["avoided"] == "Ring is avoid"
    assert "Won't fit" in reasons["huge"]
    assert "below required 32768" in reasons["short-context"]


def test_modality_filter_and_unknown_task() -> None:
    profiles = {
        "vision-model": profile(
            id="vision-model", name="Vision Model", modality="vision",
            benchmark_aggregates=[],
        ),
        "qwen3-8b": profile(),
    }

    coding = build_answers(profiles, "rtx-4090-24gb", "coding")
    assert [c["model_id"] for c in coding["candidates"]] == ["qwen3-8b"]
    # Wrong modality is a category mismatch, not an "exclusion".
    assert all(row["model_id"] != "vision-model" for row in coding["excluded"])

    vision = build_answers(profiles, "rtx-4090-24gb", "vision")
    assert [c["model_id"] for c in vision["candidates"]] == ["vision-model"]

    with pytest.raises(ValueError, match="Unknown task"):
        build_answers(profiles, "rtx-4090-24gb", "not-a-task")


def test_task_registry_uses_canonical_benchmark_keys() -> None:
    from radar.models_radar.benchmarks import CANONICAL_BENCHMARKS

    for task, spec in TASKS.items():
        unknown = set(spec["benchmarks"]) - set(CANONICAL_BENCHMARKS)
        assert not unknown, f"{task}: {unknown}"
