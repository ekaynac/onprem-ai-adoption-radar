"""The Answer Machine: task + hardware + policy → ranked, cited candidates.

Pure reduction over curated model profiles (the ``load_public_model_profiles``
shape, which embeds rings, quants, and triangulated benchmark aggregates).
Every candidate carries its six components — fit, task capability, license
gate, cost, maturity, and the factor list that produced its rank. Exclusions
are returned with reasons, never silently dropped. Unknown stays unknown:
a model without task benchmarks ranks on its curated score with an explicit
assumption, not an invented percentile.
"""

from __future__ import annotations

from typing import Any

from radar.models_radar.benchmarks import CANONICAL_BENCHMARKS
from radar.models_radar.device_fit import (
    TPS_SLOW_BELOW,
    estimate_decode_tps,
    evaluate_fit,
    performance_note,
)
from radar.models_radar.devices import DeviceProfile, resolve_device
from radar.models_radar.entities import ModelEntry


def _best_quant_bits(entry: ModelEntry, quant_format: str | None) -> float | None:
    if not quant_format:
        return None
    for quant in entry.quants:
        if quant.format == quant_format:
            return quant.bits_per_weight
    return None


ADVISOR_VERSION = "advisor-v2"

# A task-capability percentile is only defensible when it aggregates at
# least this many distinct benchmark suites. One score is a data point,
# not a ranking basis ("P100 across 1 benchmark" reads like precision
# that does not exist).
MIN_TASK_BENCHMARK_SOURCES = 2

TASKS: dict[str, dict[str, Any]] = {
    "coding": {
        "label": "Coding assistant",
        "benchmarks": [
            "aider-polyglot",
            "livecodebench",
            "livebench-coding",
            "livebench-code-completion",
            "humaneval",
            "swe-bench-verified",
        ],
        "modalities": {"text", "multimodal"},
    },
    "general-chat": {
        "label": "General chat / assistant",
        "benchmarks": ["mmlu-pro", "mmlu", "ifeval", "ollb-average"],
        "modalities": {"text", "multimodal"},
    },
    "reasoning": {
        "label": "Reasoning / analysis",
        "benchmarks": [
            "gpqa-diamond",
            "gpqa",
            "aime-2024",
            "aime-2025",
            "math-l5",
            "mmlu-pro",
        ],
        "modalities": {"text", "multimodal"},
    },
    "rag": {
        "label": "RAG over internal documents",
        "benchmarks": ["ifeval", "mmlu-pro", "bbh"],
        "modalities": {"text", "multimodal"},
    },
    "vision": {
        "label": "Vision / document understanding",
        "benchmarks": [],
        "modalities": {"multimodal", "vision"},
    },
    # No "embedding"/"speech" tasks yet: the curated catalog tracks no
    # models in those modalities, and an empty task would be a dormant
    # feature. Add the task together with the first tracked models.
}

_FIT_WEIGHTS = {
    "fits": 1.0,
    "fits_tight": 0.85,
    "fits_quantized": 0.7,
    "unknown": 0.35,
}
_RING_WEIGHTS = {"adopt": 1.0, "pilot": 0.8, "watch": 0.5}

_WEIGHT_FIT = 0.30
_WEIGHT_TASK = 0.25
_WEIGHT_RING = 0.20
_WEIGHT_MATURITY = 0.10
_WEIGHT_PERF = 0.15

# Throughput: log-shaped so 60 tok/s outranks 3 tok/s without an unbounded
# scale; 0..1 saturating at ~120 tok/s which exceeds the bandwidth-bound
# ceiling of any current device.
def _perf_score(est_tps: float | None) -> float:
    if est_tps is None or est_tps <= 0:
        return 0.0
    return min(1.0, (est_tps / 120.0) ** 0.5)


def _task_capability(
    profile: dict[str, Any],
    benchmark_keys: list[str],
) -> dict[str, Any] | None:
    rows = [
        aggregate
        for aggregate in profile.get("benchmark_aggregates") or []
        if aggregate.get("benchmark") in benchmark_keys
        and aggregate.get("percentile") is not None
    ]
    if not rows:
        return None
    percentiles = [float(row["percentile"]) for row in rows]
    distinct = len({row["benchmark"] for row in rows})
    return {
        "percentile": round(sum(percentiles) / len(percentiles)),
        "distinct_benchmarks": distinct,
        "evidence": (
            "sufficient"
            if distinct >= MIN_TASK_BENCHMARK_SOURCES
            else "single-source"
        ),
        "benchmarks": [
            {
                "benchmark": row["benchmark"],
                "label": row.get(
                    "label",
                    CANONICAL_BENCHMARKS.get(row["benchmark"], row["benchmark"]),
                ),
                "consensus": row.get("consensus"),
                "percentile": row.get("percentile"),
                "sample_size": row.get("sample_size"),
                "flagged": row.get("flagged", False),
            }
            for row in sorted(rows, key=lambda item: item["benchmark"])
        ],
    }


def _device_cost(device: DeviceProfile) -> dict[str, Any]:
    board_power_kw = (
        round(device.tdp_watts * device.gpu_count / 1000, 2)
        if device.tdp_watts
        else None
    )
    return {
        "board_power_kw": board_power_kw,
        "indicative_hardware_usd": device.indicative_price_usd,
        "note": (
            "Device-level board power and indicative list price; "
            "workload-specific $/Mtok comes from the planner"
        ),
    }


def build_answers(
    profiles: dict[str, dict[str, Any]],
    device: str | dict[str, Any],
    task: str,
    *,
    allowed_licenses: list[str] | None = None,
    min_context: int | None = None,
    limit: int = 5,
    include_unverified: bool = False,
    root: Any | None = None,
) -> dict[str, Any]:
    """Rank curated models for a task on a device under a policy.

    Evidence honesty policy (advisor-v2): candidates with task benchmarks
    from ``MIN_TASK_BENCHMARK_SOURCES`` or more distinct suites rank
    normally. Single-source models rank below every sufficient-evidence
    candidate with an explicit "insufficient evidence" label. Benchmarkless
    models are excluded by default and only surface when the caller opts in
    via ``include_unverified``.

    The task→suite mapping is not frozen: when ``root`` is given, suites
    learned in ``data/knowledge/task-suites.jsonl`` (radar.knowledge)
    extend the bundled defaults.
    """
    if task not in TASKS:
        raise ValueError(
            f"Unknown task {task!r}; expected one of {sorted(TASKS)}"
        )
    task_spec = dict(TASKS[task])
    if root is not None:
        from radar.knowledge import load_task_suite_overrides

        learned_suites = load_task_suite_overrides(root).get(task) or []
        if learned_suites:
            task_spec["benchmarks"] = [
                *task_spec["benchmarks"],
                *(
                    suite
                    for suite in learned_suites
                    if suite not in task_spec["benchmarks"]
                ),
            ]
    device_profile = resolve_device(device)
    context_tokens = min_context or 4096

    candidates: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    for model_id in sorted(profiles):
        profile = profiles[model_id]
        modality = str(profile.get("modality") or "text")
        if modality not in task_spec["modalities"]:
            continue  # a different product category, not an exclusion

        ring = profile.get("ring")
        if ring == "avoid":
            excluded.append(
                {"model_id": model_id, "reason": "Ring is avoid"}
            )
            continue

        license_value = profile.get("license")
        if allowed_licenses is not None and (
            license_value is None or license_value not in allowed_licenses
        ):
            excluded.append(
                {
                    "model_id": model_id,
                    "reason": (
                        f"License {license_value or 'unknown'} not in "
                        f"policy {sorted(allowed_licenses)}"
                    ),
                }
            )
            continue

        model_context = profile.get("context_length")
        if (
            min_context is not None
            and isinstance(model_context, int)
            and model_context < min_context
        ):
            excluded.append(
                {
                    "model_id": model_id,
                    "reason": (
                        f"Context {model_context} below required {min_context}"
                    ),
                }
            )
            continue

        entry = ModelEntry.model_validate(profile)
        fit = evaluate_fit(entry, device_profile, context_tokens)
        if fit.verdict == "wont_fit":
            excluded.append(
                {
                    "model_id": model_id,
                    "reason": f"Won't fit on {device_profile.name}",
                }
            )
            continue

        # Bandwidth-bound decode estimate: the dimension that separates
        # "fits" from "usable" on unified-memory boxes (DGX Spark, Mac
        # Studio). MoE models win here; dense 70B+ gets flagged.
        quant_bits = (
            _best_quant_bits(entry, fit.best_quant_format)
            if fit.best_quant_format
            else None
        )
        est_tps = estimate_decode_tps(entry, device_profile, quant_bits)
        perf_note = performance_note(est_tps)

        capability = _task_capability(profile, task_spec["benchmarks"])
        if not task_spec["benchmarks"]:
            # Task defines no canonical suites yet: nothing to measure
            # against, so the evidence bar does not apply.
            evidence_tier = "sufficient"
        else:
            evidence_tier = (
                "sufficient"
                if capability is not None
                and capability["evidence"] == "sufficient"
                else "single-source"
                if capability is not None
                else "none"
            )
        if evidence_tier == "none" and not include_unverified:
            excluded.append(
                {
                    "model_id": model_id,
                    "reason": (
                        "Insufficient evidence: no tracked benchmark for "
                        "this task (opt in to see curated-score guesses)"
                    ),
                }
            )
            continue

        curated_score = profile.get("score")
        maturity = (
            float(curated_score) / 5.0
            if isinstance(curated_score, int | float)
            else 0.4
        )
        fit_weight = _FIT_WEIGHTS.get(fit.verdict, 0.35)
        ring_weight = _RING_WEIGHTS.get(str(ring), 0.4)
        if capability is not None:
            # Sufficient evidence ranks on measured percentile; single-source
            # evidence is discounted hard so one benchmark never masquerades
            # as a ranking basis.
            task_weight = capability["percentile"] / 100.0
            if evidence_tier == "single-source":
                task_weight *= 0.5
        else:
            task_weight = maturity
        perf_weight = _perf_score(est_tps)
        composite = round(
            _WEIGHT_FIT * fit_weight
            + _WEIGHT_TASK * task_weight
            + _WEIGHT_RING * ring_weight
            + _WEIGHT_MATURITY * maturity
            + _WEIGHT_PERF * perf_weight,
            4,
        )

        reasons = [f"Fit: {fit.verdict} on {device_profile.name}"]
        if fit.best_quant_format:
            reasons.append(
                f"Best quant {fit.best_quant_format}"
                + (
                    f" (~{fit.best_quant_memory_gb:.1f} GB of "
                    f"{fit.usable_gb:.1f} GB usable)"
                    if fit.best_quant_memory_gb is not None
                    else ""
                )
            )
        if capability is not None:
            if evidence_tier == "sufficient":
                reasons.append(
                    f"Task capability p{capability['percentile']} across "
                    f"{len(capability['benchmarks'])} benchmark suites"
                )
            else:
                reasons.append(
                    f"Insufficient task evidence: single benchmark "
                    f"({capability['benchmarks'][0]['label']}) — ranked "
                    "below fully evidenced models"
                )
        if ring:
            reasons.append(f"Curated ring: {ring}")
        if perf_note:
            reasons.append(perf_note)
        assumptions = []
        if capability is None:
            assumptions.append(
                "No tracked benchmarks for this task — shown only because "
                "unverified candidates were requested; the curated composite "
                "score is NOT a measured ranking"
            )
        if fit.verdict == "unknown":
            assumptions.append(
                f"Fit is unknown ({fit.note or 'insufficient sizing data'}) "
                "— verify memory before committing"
            )

        candidates.append(
            {
                "model_id": model_id,
                "name": profile.get("name") or model_id,
                "release_id": f"release:legacy:{model_id}",
                "ring": ring,
                "composite": composite,
                "evidence_tier": evidence_tier,
                "estimated_tok_s": est_tps,
                "fit": {
                    "verdict": fit.verdict,
                    "best_quant_format": fit.best_quant_format,
                    "best_quant_memory_gb": fit.best_quant_memory_gb,
                    "usable_gb": fit.usable_gb,
                    "context_tokens": context_tokens,
                },
                "task_capability": capability,
                "license": {
                    "value": license_value,
                    "allowed": (
                        True
                        if allowed_licenses is None
                        else license_value in allowed_licenses
                    ),
                },
                "params_total": profile.get("params_total"),
                "params_active": profile.get("params_active"),
                "context_length": model_context,
                "maturity_score": profile.get("score"),
                "reasons": reasons,
                "assumptions": assumptions,
            }
        )

    # Evidence tier dominates the sort: fully-evidenced candidates always
    # outrank single-source guesses, regardless of composite score.
    evidence_rank = {"sufficient": 0, "single-source": 1}
    candidates.sort(
        key=lambda item: (
            evidence_rank.get(item["evidence_tier"], 2),
            -item["composite"],
            item["model_id"],
        )
    )
    ranked = candidates[:limit]
    insight = _bandwidth_insight(ranked)
    assumptions = [
        "Fit verdicts come from the deterministic capacity engine at "
        f"{context_tokens} context tokens",
        f"Task capability requires benchmarks from at least "
        f"{MIN_TASK_BENCHMARK_SOURCES} distinct suites; models below "
        "that bar are labeled insufficient evidence and ranked last",
    ]
    if insight:
        assumptions.append(insight)
    return {
        "version": ADVISOR_VERSION,
        "task": task,
        "task_label": task_spec["label"],
        "device": device_profile.name,
        "context_tokens": context_tokens,
        "min_task_benchmark_sources": MIN_TASK_BENCHMARK_SOURCES,
        "cost": _device_cost(device_profile),
        "candidates": ranked,
        "excluded": excluded,
        "assumptions": assumptions,
    }


def _bandwidth_insight(candidates: list[dict[str, Any]]) -> str | None:
    """Device-level guidance when the shortlist mixes fast and slow decodes."""
    estimated = [c["estimated_tok_s"] for c in candidates if c.get("estimated_tok_s") is not None]
    if len(estimated) < 2:
        return None
    fastest = max(estimated)
    slow = [c for c in candidates if (c.get("estimated_tok_s") or 0) < TPS_SLOW_BELOW]
    if fastest >= TPS_SLOW_BELOW and slow:
        return (
            f"Decode speed spans {fastest:g} vs {min(estimated):g} tok/s on this "
            "device's memory bandwidth — sparse/MoE architectures dominate "
            "unified-memory boxes; check each candidate's tok/s before committing"
        )
    return None
