"""Benchmark auto-ingest from Hugging Face model cards.

Parses published benchmark numbers out of an HF model card (README.md
markdown) into canonical-benchmark observations. This closes the coverage
gap left by leaderboard sweeps: a curated model whose repo publishes its
own MMLU/HumanEval/etc. table gets evidence without a human hand-editing
the seed YAML.

Parsing is deliberately conservative:
- only canonical benchmark names (and a few well-known aliases) match;
- values must be plausible percentages (0 < v <= 100);
- ambiguity (a name matching two rows) drops the match rather than guess.
"""

from __future__ import annotations

import re
from typing import Any

from radar.models_radar.benchmarks import CANONICAL_BENCHMARKS


# Model cards frequently use aliases instead of canonical keys.
_ALIASES: dict[str, str] = {
    "humaneval": "humaneval",
    "human_eval": "humaneval",
    "human-eval": "humaneval",
    "mmlu": "mmlu",
    "mmlu-pro": "mmlu-pro",
    "mmlu_pro": "mmlu-pro",
    "gpqa": "gpqa",
    "gpqa-diamond": "gpqa-diamond",
    "gpqa_diamond": "gpqa-diamond",
    "aime-2024": "aime-2024",
    "aime2024": "aime-2024",
    "aime-2025": "aime-2025",
    "aime2025": "aime-2025",
    "livecodebench": "livecodebench",
    "swe-bench": "swe-bench-verified",
    "swe-bench-verified": "swe-bench-verified",
    "ifeval": "ifeval",
    "bbh": "bbh",
    "math": "math-l5",
    "math-l5": "math-l5",
}

# | MMLU-Pro | 66.3 | ...   /   **HumanEval**: 84.8   /   HumanEval: 84.8
_TABLE_ROW = re.compile(
    r"^\s*\|?\s*\**(?P<name>[A-Za-z][A-Za-z0-9 ._\-]{1,30})\**\s*\|+\s*"
    r"\**(?P<score>\d{1,3}(?:\.\d+)?)\**\s*(?:%|\|)",
    re.MULTILINE,
)
_INLINE = re.compile(
    r"\**(?P<name>[A-Za-z][A-Za-z0-9 ._\-]{2,30})\**\s*[:=]\s*"
    r"\**(?P<score>\d{1,3}(?:\.\d+)?)\s*(?:%|points?)?\b"
)

_PERCENT = re.compile(r"^\d{1,3}(?:\.\d+)?$")


def _canonical(name: str) -> str | None:
    key = name.strip().lower().replace(" ", "-").replace("_", "-")
    key = re.sub(r"-+", "-", key).strip("-")
    candidates = [key]
    # Inline prose glues conjunctions onto names ("and GPQA-Diamond");
    # try the trailing 1-2 tokens so prose context cannot hide a hit.
    parts = key.split("-")
    if len(parts) > 1:
        candidates.append("-".join(parts[-1:]))
        if len(parts) > 2:
            candidates.append("-".join(parts[-2:]))
    for candidate in candidates:
        alias = _ALIASES.get(candidate)
        if alias:
            return alias
        if candidate in CANONICAL_BENCHMARKS:
            return candidate
    return None


def parse_card_benchmarks(card_text: str) -> dict[str, tuple[float, str]]:
    """Extract ``{canonical_key: (score, matched_name)}`` from markdown.

    Table matches win over inline ones (tables are how HF cards publish
    evals); within each strategy the last unambiguous row wins.
    """
    if not card_text:
        return {}
    found: dict[str, tuple[float, str]] = {}

    def _consider(match: re.Match[str]) -> None:
        raw_name = match.group("name").strip()
        raw_score = match.group("score").strip()
        if not _PERCENT.match(raw_score):
            return
        score = float(raw_score)
        if not 0 < score <= 100:
            return
        key = _canonical(raw_name)
        if key:
            found[key] = (score, raw_name)

    for match in _TABLE_ROW.finditer(card_text):
        _consider(match)
    tables = dict(found)
    found.clear()
    for match in _INLINE.finditer(card_text):
        _consider(match)
    # Prefer table rows where both strategies matched.
    merged = {**found, **tables}
    return merged


def benchmark_debt(
    seeds_by_id: dict[str, Any],
    aggregates_by_model: dict[str, list[dict[str, Any]]],
    tasks: dict[str, dict[str, Any]],
    *,
    min_sources: int = 2,
) -> list[dict[str, Any]]:
    """Which tracked models lack sufficient task evidence, and for what.

    Returns one row per (model, task) where the model is relevant by
    modality but has fewer than ``min_sources`` distinct canonical suites
    among the task's benchmarks — the worklist for ingest sweeps.
    """
    rows: list[dict[str, Any]] = []
    for model_id in sorted(seeds_by_id):
        profile = seeds_by_id[model_id]
        modality = str(getattr(profile, "modality", None) or "text")
        have = {
            row.get("benchmark") for row in aggregates_by_model.get(model_id, [])
        }
        for task_key, spec in tasks.items():
            suites = spec["benchmarks"]
            if not suites or modality not in spec["modalities"]:
                continue
            missing = [suite for suite in suites if suite not in have]
            distinct_have = len(suites) - len(missing)
            if distinct_have >= min_sources:
                continue
            rows.append(
                {
                    "model_id": model_id,
                    "task": task_key,
                    "have": sorted(have & set(suites)),
                    "missing": missing[:6],
                    "distinct_have": distinct_have,
                    "needed": min_sources,
                }
            )
    return rows
