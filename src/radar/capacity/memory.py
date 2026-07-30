"""Per-rank memory accounting + TP/PP/EP sharding feasibility (spec §6).

This is the layer the solver (Task 5) searches over: given a candidate
``Parallelism`` layout and a ``DeviceProfile``, compute what a single rank
(one GPU's share of the deployment) actually has to hold, and whether that
fits in the GPU's usable memory.

Per-rank math (documented here, not just in the docstring below, because the
worked test numbers in ``tests/test_capacity_memory.py`` are the contract):

- Pipeline parallelism does NOT require an even layer split (ruling
  2026-07-30: real engines — vLLM, TensorRT-LLM — support uneven pipeline
  stages; DeepSeek-class 61-layer checkpoints are routinely served at
  ``pp=2`` as 31+30). Instead we model the LARGEST stage, since that's the
  one every rank's memory budget must accommodate:
  ``stage_fraction = ceil(num_layers / pp) / num_layers`` when ``pp > 1``
  and ``num_layers`` is known; ``1.0`` otherwise (``pp == 1``, or the
  layer count is unknown — the latter case never reaches this line because
  ``check_sharding`` already rejects ``pp > 1`` with an unknown layer count
  before ``plan_memory`` computes anything).
- ``weights_per_rank = weights_gb * stage_fraction / (tensor_parallel *
  expert_parallel)`` where ``weights_gb = params_total * bits_per_weight / 8
  / 1e9``. For MoE models, EP shards the routed-expert weights ~evenly; this
  is an honest simplification — shared/dense layers' replicated cost is not
  itemized separately (see the assumption note emitted below). When
  ``pp == 1`` or the layers split evenly, ``stage_fraction`` collapses to
  ``1 / pipeline_parallel`` and this reduces exactly to the old
  ``weights_gb / world_size`` — verified as an invariant in
  ``tests/test_capacity_memory.py``.
- ``kv_per_rank = kv_gb(bytes_per_token, ctx, concurrency) * stage_fraction /
  tensor_parallel``. KV shards over TP (each TP rank holds a fraction of the
  attention heads' KV). Each pipeline stage only holds the KV for the layers
  it owns, so the largest stage's ``stage_fraction`` scales the KV term too
  — same collapse-to-``/(tp*pp)`` invariant when layers split evenly. This
  models request-distributed KV (data-parallel-attention-style serving,
  e.g. vLLM's DP-attention for MLA/MQA), which is how narrow-kv-head models
  actually deploy at scale — not a naive pure-TP replication of the whole KV
  cache onto every rank. When ``tensor_parallel`` exceeds the KV head count
  (MLA, or GQA/HYBRID with few kv_heads, e.g. MQA's ``kv_heads=1``),
  pure-TP would replicate KV per rank instead of dividing it; the
  assumption note below discloses that gap whenever it applies. An uneven
  split (``num_layers % pp != 0``) adds its own disclosure note naming the
  largest stage's share.
- ``baseline_gb = RUNTIME_BASELINE_GB`` (fixed per-rank engine/CUDA-context
  footprint, reused from ``radar.models_radar.memory`` rather than
  redefined).
- ``fragmentation_gb = 0.05 * (weights_per_rank + kv_per_rank)`` — itemized
  as its own field. This is deliberately not the estimator's ``× 1.05``
  shorthand: per-rank accounting needs the fragmentation term visible on its
  own so callers (and the solver) can reason about where the memory goes.
- ``total_gb = weights_per_rank + kv_per_rank + baseline_gb + fragmentation_gb``.
- ``usable_per_gpu_gb = device.total_memory_gb * USABLE_FRACTION[device.kind]``
  — per SINGLE gpu, deliberately NOT multiplied by ``device.gpu_count``
  (unlike ``models_radar.devices.usable_memory_gb``): the solver owns how
  many GPUs to use, this module owns what one of them has to hold.
- ``fits = total_gb <= usable_per_gpu_gb``; ``headroom_fraction = (usable -
  total) / usable`` (negative when over budget).

Sharding feasibility (``check_sharding``) is checked first: TP requires the
KV head count to divide evenly (MLA is exempt — its latent cache is
replicated per rank, not sharded by head, so TP never fragments it); EP
requires a known, evenly-divisible expert count; PP requires a known layer
count (can't size stages otherwise) and at most one layer's worth of
stages (``pp <= num_layers``) — it no longer requires even divisibility
(see the largest-stage modeling above). Any problem found there means
``plan_memory`` cannot produce a meaningful per-rank plan and raises
``InfeasibleError`` instead of a ``MemoryPlan`` with nonsense numbers.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict

from radar.capacity.kv import kv_bytes_per_token, kv_gb
from radar.capacity.types import AssumptionSheet, Parallelism, Workload
from radar.models_radar.devices import USABLE_FRACTION, DeviceProfile
from radar.models_radar.entities import ArchitectureSpec
from radar.models_radar.memory import RUNTIME_BASELINE_GB  # shared constant, not redefined


FRAGMENTATION_FRACTION = 0.05  # weights+kv packing/alignment slack, itemized per-rank


class RankMemory(BaseModel):
    """What a single rank (one GPU's share) has to hold."""

    model_config = ConfigDict(frozen=True)

    weights_gb: float
    kv_gb: float
    baseline_gb: float
    fragmentation_gb: float
    total_gb: float


class MemoryPlan(BaseModel):
    """A per-rank memory plan for one candidate parallelism layout on one device."""

    model_config = ConfigDict(frozen=True)

    per_rank: RankMemory
    usable_per_gpu_gb: float
    fits: bool
    headroom_fraction: float
    assumptions: AssumptionSheet


class InfeasibleError(ValueError):
    """Raised by ``plan_memory`` when ``check_sharding`` finds problems.

    Carries structured reasons — never raised empty.
    """

    def __init__(self, reasons: list[str]) -> None:
        if not reasons:
            raise ValueError("InfeasibleError must be raised with at least one reason")
        self.reasons: list[str] = list(reasons)
        super().__init__("Infeasible sharding plan: " + "; ".join(self.reasons))


def check_sharding(
    architecture: ArchitectureSpec | None,
    num_layers: int | None,
    parallelism: Parallelism,
) -> list[str]:
    """Return sharding problem strings for this layout (empty = feasible).

    - TP: ``num_key_value_heads`` and ``tensor_parallel`` must be cleanly
      compatible — either ``kv_heads`` splits evenly across ranks
      (``kv_heads >= tp`` and ``kv_heads % tp == 0``) or ranks evenly share
      replicated heads (``kv_heads < tp`` and ``tp % kv_heads == 0``, the
      standard MQA/narrow-GQA case, e.g. ``kv_heads=1``). The architecture is
      exempt from this check entirely when it is MLA (``kv_lora_rank`` set)
      — MLA's compressed latent cache is replicated per rank rather than
      sharded by head, so TP divisibility of kv_heads is not a real
      constraint for it.
    - EP: ``num_experts`` must be known and divide evenly by
      ``expert_parallel``.
    - PP: ``num_layers`` must be known (can't size pipeline stages without
      it) and ``pipeline_parallel`` must not exceed it (more stages than
      layers is meaningless). Even divisibility is NOT required — real
      engines (vLLM, TensorRT-LLM) support uneven pipeline stages, and
      ``plan_memory`` models the largest stage rather than assuming an even
      split (ruling 2026-07-30; see the module docstring).
    """
    problems: list[str] = []
    tp = parallelism.tensor_parallel
    pp = parallelism.pipeline_parallel
    ep = parallelism.expert_parallel

    if tp > 1 and architecture is not None:
        is_mla = architecture.kv_lora_rank is not None
        kv_heads = architecture.num_key_value_heads
        if not is_mla and kv_heads is not None and kv_heads > 0:
            bigger, smaller = max(kv_heads, tp), min(kv_heads, tp)
            if bigger % smaller != 0:
                problems.append(
                    f"tensor_parallel={tp} and kv_heads={kv_heads} are not "
                    "cleanly compatible for TP sharding (neither evenly "
                    "divides the other)"
                )

    if ep > 1:
        num_experts = architecture.num_experts if architecture is not None else None
        if num_experts is None:
            problems.append("expert parallelism requested but expert count unknown")
        elif num_experts % ep != 0:
            problems.append(
                f"expert_parallel={ep} does not evenly divide num_experts={num_experts}"
            )

    if pp > 1:
        if num_layers is None:
            problems.append(
                "pipeline parallelism requested but layer count unknown — cannot size stages"
            )
        elif pp > num_layers:
            problems.append(
                f"pipeline_parallel={pp} exceeds num_layers={num_layers} "
                "(more stages than layers)"
            )

    return problems


def plan_memory(
    *,
    params_total: int,
    bits_per_weight: float,
    architecture: ArchitectureSpec | None,
    num_layers: int | None,
    hidden_size: int | None,
    workload: Workload,
    parallelism: Parallelism,
    device: DeviceProfile,
    kv_dtype: str = "fp16",
) -> MemoryPlan:
    """Per-rank memory accounting for one parallelism layout on one device.

    See the module docstring for the full math. Raises ``InfeasibleError``
    when ``check_sharding`` finds problems; otherwise always returns a
    ``MemoryPlan`` — ``fits=False`` is a valid, non-error result.
    """
    problems = check_sharding(architecture, num_layers, parallelism)
    if problems:
        raise InfeasibleError(problems)

    tp = parallelism.tensor_parallel
    pp = parallelism.pipeline_parallel
    ep = parallelism.expert_parallel

    # Largest-stage modeling (ruling 2026-07-30): every rank's budget must
    # accommodate the biggest pipeline stage, not an assumed-even average.
    # pp==1 (or an unknown layer count, which check_sharding already
    # rejects whenever pp>1) collapses stage_fraction to 1.0, and an even
    # split collapses it to exactly 1/pp — both reduce to the pre-ruling
    # math (weights_gb/world_size, kv_total/(tp*pp)); see
    # tests/test_capacity_memory.py for the invariant check.
    largest_stage_layers: int | None = None
    if pp > 1 and num_layers is not None:
        largest_stage_layers = math.ceil(num_layers / pp)
        stage_fraction = largest_stage_layers / num_layers
    else:
        stage_fraction = 1.0

    weights_gb = params_total * bits_per_weight / 8 / 1e9
    weights_per_rank = weights_gb * stage_fraction / (tp * ep)

    bytes_per_token, kv_notes = kv_bytes_per_token(
        architecture, num_layers=num_layers, hidden_size=hidden_size, kv_dtype=kv_dtype
    )
    kv_total_gb = (
        kv_gb(bytes_per_token, workload.avg_context_tokens, workload.concurrent_requests)
        if bytes_per_token is not None
        else 0.0
    )
    kv_per_rank = kv_total_gb * stage_fraction / tp

    baseline_gb = RUNTIME_BASELINE_GB
    fragmentation_gb = FRAGMENTATION_FRACTION * (weights_per_rank + kv_per_rank)
    total_gb = weights_per_rank + kv_per_rank + baseline_gb + fragmentation_gb

    per_rank = RankMemory(
        weights_gb=weights_per_rank,
        kv_gb=kv_per_rank,
        baseline_gb=baseline_gb,
        fragmentation_gb=fragmentation_gb,
        total_gb=total_gb,
    )

    usable_per_gpu_gb = device.total_memory_gb * USABLE_FRACTION[device.kind]
    headroom_fraction = (usable_per_gpu_gb - total_gb) / usable_per_gpu_gb
    fits = total_gb <= usable_per_gpu_gb

    assumptions = AssumptionSheet().plus(
        "Weights: EP shards routed-expert weights ~evenly for MoE — honest "
        "simplification; shared/dense layers' replicated cost is not itemized",
        *kv_notes,
    )
    if largest_stage_layers is not None and num_layers is not None and num_layers % pp != 0:
        assumptions = assumptions.plus(
            f"pipeline stages uneven: largest stage {largest_stage_layers}/{num_layers} "
            "layers modeled (ceil)"
        )
    if (
        architecture is not None
        and architecture.kv_lora_rank is not None
        and parallelism.tensor_parallel > 1
    ):
        assumptions = assumptions.plus(
            "MLA latent KV cache: pure-TP serving replicates the whole latent "
            "cache per rank (it isn't sharded by head) — estimate assumes "
            "request-distributed KV (data-parallel attention); pure-TP "
            "per-rank KV would be higher"
        )
    elif (
        architecture is not None
        and architecture.kv_lora_rank is None
        and architecture.num_key_value_heads is not None
        and parallelism.tensor_parallel > architecture.num_key_value_heads
    ):
        assumptions = assumptions.plus(
            f"KV heads ({architecture.num_key_value_heads}) < tensor_parallel "
            f"({parallelism.tensor_parallel}): pure-TP serving replicates KV per "
            "rank — estimate assumes request-distributed KV (data-parallel "
            "attention); pure-TP per-rank KV would be higher"
        )

    return MemoryPlan(
        per_rank=per_rank,
        usable_per_gpu_gb=usable_per_gpu_gb,
        fits=fits,
        headroom_fraction=headroom_fraction,
        assumptions=assumptions,
    )
