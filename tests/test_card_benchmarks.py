from __future__ import annotations

from radar.models_radar.advisor import TASKS
from radar.models_radar.card_benchmarks import (
    benchmark_debt,
    parse_card_benchmarks,
)


def test_parses_markdown_table_scores() -> None:
    card = """
# Mistral-like model

Some prose about the model.

| Benchmark | Score |
| --------- | ----- |
| MMLU-Pro  | 66.3  |
| HumanEval | 84.8  |
| IFeval    | 82.9  |
"""
    parsed = parse_card_benchmarks(card)
    assert parsed["mmlu-pro"][0] == 66.3
    assert parsed["humaneval"][0] == 84.8
    assert parsed["ifeval"][0] == 82.9


def test_parses_inline_bold_scores() -> None:
    card = "Results: **MMLU**: 88.5 and GPQA-Diamond: 71.5 on our evals."
    parsed = parse_card_benchmarks(card)
    assert parsed["mmlu"][0] == 88.5
    assert parsed["gpqa-diamond"][0] == 71.5


def test_ignores_non_canonical_and_implausible_values() -> None:
    card = """
| Downloads | 1000000 |
| MMLU      | 0.71    |
| License   | 42      |
"""
    parsed = parse_card_benchmarks(card)
    # Fraction-style scores are NOT auto-scaled here (normalize_score owns
    # that at aggregate time) — a bare 0.71 in (0,1] would be scaled later;
    # but "Downloads"/"License" never map to canonical keys at all.
    assert set(parsed) <= {"mmlu"}


def test_table_row_beats_inline_duplicate() -> None:
    card = """
Old blog said LiveCodeBench: 51.2

| Benchmark     | Score |
| ------------- | ----- |
| LiveCodeBench | 55.4  |
"""
    parsed = parse_card_benchmarks(card)
    assert parsed["livecodebench"] == (55.4, "LiveCodeBench")


def test_benchmark_debt_lists_gaps_per_task() -> None:
    class Seed:
        def __init__(self, modality: str) -> None:
            self.modality = modality

    seeds = {"model-a": Seed("text"), "vision-b": Seed("vision")}
    aggregates = {
        "model-a": [{"benchmark": "aider-polyglot"}],
    }
    rows = benchmark_debt(seeds, aggregates, TASKS)
    coding_rows = [row for row in rows if row["task"] == "coding"]
    assert any(
        row["model_id"] == "model-a" and row["distinct_have"] < 2
        for row in coding_rows
    )
    # vision task defines no suites → never in debt
    assert not [row for row in rows if row["task"] == "vision"]


def test_category_to_modality_mapping_covers_all_categories() -> None:
    from radar.models_radar.discovered_profiles import _CATEGORY_MODALITY
    from radar.models_radar.entities import Modality

    valid = {member.value for member in Modality}
    for category, modality in _CATEGORY_MODALITY.items():
        assert modality in valid, f"{category} -> invalid modality {modality}"
