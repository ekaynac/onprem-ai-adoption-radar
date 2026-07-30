"""Deterministic memory estimation and hardware-tier classification.

Pure functions: identical inputs → identical output. The KV-cache term now
comes from ``capacity.kv.kv_bytes_per_token``, which dispatches on the model's
actual attention geometry (MLA/GQA/legacy-MHA-bound) instead of assuming a
single non-GQA upper bound. These numbers are the substrate the hardware-
device-matching phase compares to a machine.
"""

from __future__ import annotations

from radar.capacity.kv import kv_bytes_per_token, kv_gb
from radar.models_radar.entities import ArchitectureSpec, HardwareTier, QuantVariant


# spec §6.1: engine overhead is a fixed few GB per rank, not a 20% proportional
# tax. Replaces the flat OVERHEAD = 1.2 multiplier.
FRAGMENTATION = 1.05        # weight-tensor packing/alignment slack
RUNTIME_BASELINE_GB = 1.5   # fixed engine/CUDA-context footprint per rank
VIABLE_MIN_BITS = 4.0
# (max_gb_inclusive, tier) ordered ascending; first match wins.
TIER_THRESHOLDS: list[tuple[float, HardwareTier]] = [
    (16.0, HardwareTier.LAPTOP),
    (32.0, HardwareTier.APPLE_HIGH_RAM),
    (48.0, HardwareTier.SINGLE_GPU),
    (120.0, HardwareTier.WORKSTATION),
    # 163.2 = usable GB of one B200/MI300X (192 * 0.85): the largest single
    # datacenter accelerator. 950 ≈ usable GB of one 8xH200 HGX node.
    (163.0, HardwareTier.SINGLE_GPU_DC),
    (950.0, HardwareTier.SINGLE_NODE),
]


def estimate_memory_gb(
    params_total: int | None,
    bits_per_weight: float,
    context: int,
    num_layers: int | None,
    hidden_size: int | None,
    architecture: ArchitectureSpec | None = None,
) -> float | None:
    """Estimated RAM/VRAM (GB) to run the model at ``context`` tokens.

    Weights term always applies (× FRAGMENTATION, for tensor packing/alignment
    slack). KV-cache term comes from the architecture-correct dispatch in
    ``capacity.kv.kv_bytes_per_token`` (MLA latent cache → GQA per-head cache →
    legacy MHA upper bound from hidden_size → unmodeled/0.0 when nothing is
    known). RUNTIME_BASELINE_GB is a fixed per-rank engine footprint, added
    regardless of scale.
    """
    if params_total is None:
        return None
    weights_gb = params_total * bits_per_weight / 8 / 1e9
    bytes_per_token, _ = kv_bytes_per_token(
        architecture, num_layers=num_layers, hidden_size=hidden_size, kv_dtype="fp16"
    )
    kv_cache_gb = kv_gb(bytes_per_token, context) if bytes_per_token is not None else 0.0
    return round(weights_gb * FRAGMENTATION + kv_cache_gb + RUNTIME_BASELINE_GB, 2)


def minimum_viable_quant(quants: list[QuantVariant]) -> QuantVariant | None:
    """Smallest-memory quant at or above the quality floor, or None.

    Only considers quants with a computed ``est_memory_gb_4k`` and
    ``bits_per_weight >= VIABLE_MIN_BITS``.
    """
    viable = [
        q for q in quants
        if q.est_memory_gb_4k is not None and q.bits_per_weight >= VIABLE_MIN_BITS
    ]
    if not viable:
        return None
    return min(viable, key=lambda q: q.est_memory_gb_4k)  # type: ignore[arg-type,return-value]


def hardware_tier(min_memory_gb: float | None) -> HardwareTier:
    """Classify a model by its minimum-viable-quant memory."""
    if min_memory_gb is None:
        return HardwareTier.UNKNOWN
    for ceiling, tier in TIER_THRESHOLDS:
        if min_memory_gb <= ceiling:
            return tier
    return HardwareTier.MULTI_NODE
