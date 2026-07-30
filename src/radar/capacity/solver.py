"""Capacity solver: GPU counts from workloads, workloads from fleets (spec §6).

This is the layer the rest of the capacity engine exists to feed: given a
``ModelEntry`` and a target ``Workload``, ``plan_capacity`` searches ascending
GPU counts for the smallest deployment that both fits in memory
(``radar.capacity.memory``) and — when a throughput target is set — clears it
(``radar.capacity.throughput``). ``max_workload`` runs the search in the other
direction: fixed fleet size, largest concurrency it can serve.

Candidate GPU counts (ascending, first fit wins):

- ``device.gpu_count == 1`` (a bare accelerator preset): ``1, 2, 4, 8``, then
  node-sized steps of 8 up to ``_MAX_GPUS`` (512) — the search explores
  scaling that accelerator into a fleet, not just "does one fit".
- ``device.gpu_count == G > 1`` (a node/cluster preset): multiples of ``G``
  (``G, 2G, 3G, ...``) up to ``_MAX_GPUS``.

Layout heuristic (pinned, not searched over): ``tensor_parallel=min(count,
8)``, ``pipeline_parallel=count // 8 or 1``, ``expert_parallel=1`` — TP stays
within one NVLink-domain-sized (8-GPU) node, PP crosses node boundaries; EP is
never auto-selected. Disclosed verbatim as an assumption line on every
returned plan. A candidate count whose layout fails
``radar.capacity.memory.check_sharding`` is skipped (not retried with a
different split — the heuristic is the contract); its reasons are kept in
case every candidate is exhausted, in which case they become the
``InfeasibleError``.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from radar.capacity.kv import kv_bytes_per_token
from radar.capacity.memory import InfeasibleError, MemoryPlan, check_sharding, plan_memory
from radar.capacity.throughput import ThroughputEstimate, estimate_throughput
from radar.capacity.types import AssumptionSheet, Parallelism, Workload
from radar.mcp_server.model_queries import load_platform_entries
from radar.models_radar.assemble import _BITS_BY_FORMAT, bits_for_format
from radar.models_radar.devices import DeviceProfile, resolve_device
from radar.models_radar.entities import AttentionKind, ModelEntry
from radar.models_radar.memory import VIABLE_MIN_BITS
from radar.models_radar.platform_matrix import PlatformMatrixError


_REPO_ROOT = Path(__file__).resolve().parents[3]
_MAX_GPUS = 512
_LAYOUT_HEURISTIC_NOTE = (
    "layout heuristic: TP<=8 intra-node, PP across nodes; EP not auto-selected"
)


class CapacityPlan(BaseModel):
    """The smallest deployment shape (GPU count + layout) that serves a workload."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    device_id: str
    n_gpus: int
    n_nodes: int | None
    parallelism: Parallelism
    memory: MemoryPlan
    throughput: ThroughputEstimate | None
    meets_target: bool | None
    assumptions: AssumptionSheet


class MaxWorkload(BaseModel):
    """The largest concurrency a fixed fleet can serve at a given context length."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    device_id: str
    n_gpus: int
    max_concurrent_at_context: int
    per_user_decode_tps_at_max: float | None
    assumptions: AssumptionSheet


def _dedupe(*groups: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Flatten assumption-line groups, dropping repeats, preserving first order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for group in groups:
        for line in group:
            if line not in seen:
                seen.add(line)
                ordered.append(line)
    return tuple(ordered)


def _select_quant(entry: ModelEntry, quant_format: str | None) -> tuple[float, str, list[str]]:
    """Resolve bits-per-weight for this plan. Returns (bits, label, assumption notes).

    ``quant_format`` given: match case-insensitively by substring against the
    entry's catalog quants first; if nothing matches but the string is a
    known format key (e.g. "FP8"), fall back to its nominal bits with a note
    disclosing the gap. ``quant_format=None``: pick the highest-bits catalog
    quant at or above ``VIABLE_MIN_BITS``. Either path raises
    ``InfeasibleError`` (never silently guesses) when nothing usable exists.
    """
    if quant_format is None:
        if not entry.quants:
            raise InfeasibleError([f"model {entry.id!r} has no quantization variants at all"])
        viable = [q for q in entry.quants if q.bits_per_weight >= VIABLE_MIN_BITS]
        if not viable:
            raise InfeasibleError([
                f"no quant with bits_per_weight >= {VIABLE_MIN_BITS} (VIABLE_MIN_BITS) for "
                f"{entry.id!r}; available: {', '.join(q.format for q in entry.quants)}"
            ])
        best = max(viable, key=lambda q: q.bits_per_weight)
        return (
            best.bits_per_weight,
            best.format,
            [
                f"no quant_format specified — using highest-bits viable quant "
                f"{best.format!r} ({best.bits_per_weight} bits/weight, >= {VIABLE_MIN_BITS} floor)"
            ],
        )

    low = quant_format.lower()
    for q in entry.quants:
        if low in q.format.lower():
            return (
                q.bits_per_weight,
                q.format,
                [
                    f"quant_format {quant_format!r} matched catalog entry {q.format!r} "
                    f"({q.bits_per_weight} bits/weight)"
                ],
            )

    if any(key in low for key in _BITS_BY_FORMAT):
        bits = bits_for_format(quant_format)
        return (
            bits,
            quant_format,
            [f"quant {quant_format} not in catalog for this entry — using {bits} bits/weight nominal"],
        )

    raise InfeasibleError([
        f"quant_format {quant_format!r} not found for {entry.id!r} and not a recognized "
        f"format; available quants: {', '.join(q.format for q in entry.quants) or '(none)'}"
    ])


def _candidate_counts(device: DeviceProfile) -> list[int]:
    """Ascending GPU counts to try, per the module docstring's search rule."""
    g = device.gpu_count
    if g <= 1:
        counts = [1, 2, 4, 8]
        counts.extend(range(16, _MAX_GPUS + 1, 8))
        return counts
    counts = []
    n = g
    while n <= _MAX_GPUS:
        counts.append(n)
        n += g
    return counts


def _layout_for_count(count: int) -> Parallelism:
    """The pinned canonical layout for a candidate GPU count."""
    tp = min(count, 8)
    pp = count // 8 or 1
    return Parallelism(tensor_parallel=tp, pipeline_parallel=pp, expert_parallel=1)


def _n_nodes(count: int, device: DeviceProfile) -> int | None:
    return count // device.gpu_count if device.gpu_count > 1 else None


def _platform_warnings(entry: ModelEntry, engine: str, resolved_quant_label: str) -> list[str]:
    """Advisory-only WARNING lines from the platform capability matrix.

    Never a hard failure: a missing/corrupt matrix is swallowed silently
    (the matrix is optional context, not a dependency of the math above).
    """
    try:
        platforms = load_platform_entries(_REPO_ROOT)
    except PlatformMatrixError:
        return []

    platform = next((p for p in platforms if p.id == engine), None)
    if platform is None:
        return []

    notes: list[str] = []
    if entry.architecture is not None and entry.architecture.attention_kind is AttentionKind.MLA:
        support = platform.features.get("mla", "unknown")
        if support == "no":
            notes.append(f"WARNING: {engine} platform matrix lists mla: {support}")

    low = resolved_quant_label.lower()
    dtype_feature = "nvfp4" if "nvfp4" in low else ("fp8" if "fp8" in low else None)
    if dtype_feature is not None:
        support = platform.features.get(dtype_feature, "unknown")
        if support in ("no", "partial"):
            notes.append(f"WARNING: {engine} platform matrix lists {dtype_feature}: {support}")

    return notes


def plan_capacity(
    entry: ModelEntry,
    device_spec: str,
    workload: Workload,
    *,
    quant_format: str | None = None,
    kv_dtype: str = "fp16",
    engine: str = "vllm",
) -> CapacityPlan:
    """Smallest GPU count (+ layout) on ``device_spec`` that serves ``workload``.

    Raises ``InfeasibleError`` when no candidate up to ``_MAX_GPUS`` both fits
    in memory and (when a target is set) clears it — the accumulated reasons
    include the shortfall at the largest count tried.
    """
    if entry.params_total is None:
        raise InfeasibleError([f"model {entry.id!r} has no params_total resolved — cannot plan capacity"])
    params_total: int = entry.params_total

    device = resolve_device(device_spec)
    bits, resolved_label, quant_notes = _select_quant(entry, quant_format)
    bytes_per_token, _kv_notes = kv_bytes_per_token(
        entry.architecture, num_layers=entry.num_layers, hidden_size=entry.hidden_size, kv_dtype=kv_dtype,
    )
    platform_notes = _platform_warnings(entry, engine, resolved_label)
    target = workload.target_tokens_per_sec_per_user

    last_reasons: list[str] = []
    for count in _candidate_counts(device):
        parallelism = _layout_for_count(count)
        sharding_problems = check_sharding(entry.architecture, entry.num_layers, parallelism)
        if sharding_problems:
            last_reasons = sharding_problems
            continue

        memory = plan_memory(
            params_total=params_total,
            bits_per_weight=bits,
            architecture=entry.architecture,
            num_layers=entry.num_layers,
            hidden_size=entry.hidden_size,
            workload=workload,
            parallelism=parallelism,
            device=device,
            kv_dtype=kv_dtype,
        )
        if not memory.fits:
            last_reasons = [
                f"n_gpus={count}: memory shortfall — per-rank total "
                f"{memory.per_rank.total_gb:.2f} GB > usable {memory.usable_per_gpu_gb:.2f} GB/GPU"
            ]
            continue

        throughput = estimate_throughput(
            params_active=entry.params_active,
            params_total=params_total,
            bits_per_weight=bits,
            kv_bytes_per_token=bytes_per_token,
            workload=workload,
            device=device,
            n_gpus=count,
            engine=engine,
        )

        if target is not None and (throughput is None or throughput.per_user_decode_tps < target):
            got = "unknown (no bandwidth model for this device)" if throughput is None \
                else f"{throughput.per_user_decode_tps} tok/s/user"
            last_reasons = [f"n_gpus={count}: throughput {got} does not meet target {target} tok/s/user"]
            continue

        meets_target = None if target is None or throughput is None else (
            throughput.per_user_decode_tps >= target
        )
        assumptions = AssumptionSheet(lines=_dedupe(
            memory.assumptions.lines,
            throughput.assumptions.lines if throughput is not None else (),
            quant_notes,
            (_LAYOUT_HEURISTIC_NOTE,),
            platform_notes,
        ))
        return CapacityPlan(
            model_id=entry.id,
            device_id=device_spec,
            n_gpus=count,
            n_nodes=_n_nodes(count, device),
            parallelism=parallelism,
            memory=memory,
            throughput=throughput,
            meets_target=meets_target,
            assumptions=assumptions,
        )

    if not last_reasons:
        last_reasons = [f"no candidate GPU count up to {_MAX_GPUS} was evaluated"]
    raise InfeasibleError(last_reasons)


def max_workload(
    entry: ModelEntry,
    device_spec: str,
    n_gpus: int,
    *,
    avg_context_tokens: int,
    quant_format: str | None = None,
    kv_dtype: str = "fp16",
    engine: str = "vllm",
) -> MaxWorkload:
    """Largest concurrency ``n_gpus`` can serve at ``avg_context_tokens``.

    Binary-searches concurrency 1..100_000 for the largest ``B`` where
    ``plan_memory(...).fits`` at the fixed ``n_gpus`` (same layout heuristic
    as ``plan_capacity``). Raises ``InfeasibleError`` if even ``B=1`` doesn't
    fit.
    """
    if entry.params_total is None:
        raise InfeasibleError([f"model {entry.id!r} has no params_total resolved — cannot plan capacity"])
    params_total: int = entry.params_total

    device = resolve_device(device_spec)
    bits, resolved_label, quant_notes = _select_quant(entry, quant_format)
    parallelism = _layout_for_count(n_gpus)
    sharding_problems = check_sharding(entry.architecture, entry.num_layers, parallelism)
    if sharding_problems:
        raise InfeasibleError(sharding_problems)

    def _plan_at(concurrency: int) -> MemoryPlan:
        workload = Workload(concurrent_requests=concurrency, avg_context_tokens=avg_context_tokens)
        return plan_memory(
            params_total=params_total,
            bits_per_weight=bits,
            architecture=entry.architecture,
            num_layers=entry.num_layers,
            hidden_size=entry.hidden_size,
            workload=workload,
            parallelism=parallelism,
            device=device,
            kv_dtype=kv_dtype,
        )

    plan_at_one = _plan_at(1)
    if not plan_at_one.fits:
        raise InfeasibleError([
            f"n_gpus={n_gpus}: memory shortfall — does not fit even at concurrency=1 "
            f"(per-rank total {plan_at_one.per_rank.total_gb:.2f} GB > "
            f"usable {plan_at_one.usable_per_gpu_gb:.2f} GB/GPU)"
        ])

    lo, hi = 1, 100_000
    best, best_plan = lo, plan_at_one
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = _plan_at(mid)
        if candidate.fits:
            best, best_plan = mid, candidate
            lo = mid + 1
        else:
            hi = mid - 1

    bytes_per_token, _kv_notes = kv_bytes_per_token(
        entry.architecture, num_layers=entry.num_layers, hidden_size=entry.hidden_size, kv_dtype=kv_dtype,
    )
    throughput = estimate_throughput(
        params_active=entry.params_active,
        params_total=params_total,
        bits_per_weight=bits,
        kv_bytes_per_token=bytes_per_token,
        workload=Workload(concurrent_requests=best, avg_context_tokens=avg_context_tokens),
        device=device,
        n_gpus=n_gpus,
        engine=engine,
    )
    platform_notes = _platform_warnings(entry, engine, resolved_label)

    assumptions = AssumptionSheet(lines=_dedupe(
        best_plan.assumptions.lines,
        throughput.assumptions.lines if throughput is not None else (),
        quant_notes,
        (_LAYOUT_HEURISTIC_NOTE,),
        platform_notes,
    ))
    return MaxWorkload(
        model_id=entry.id,
        device_id=device_spec,
        n_gpus=n_gpus,
        max_concurrent_at_context=best,
        per_user_decode_tps_at_max=throughput.per_user_decode_tps if throughput is not None else None,
        assumptions=assumptions,
    )
