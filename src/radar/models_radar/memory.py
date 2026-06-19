"""Deterministic memory estimation and hardware-tier classification.

Pure functions: identical inputs → identical output. The KV-cache term is a
non-GQA upper bound, so estimates lean high rather than low. These numbers are
the substrate the future hardware-device-matching phase compares to a machine.
"""

from __future__ import annotations

from radar.models_radar.entities import HardwareTier, QuantVariant


OVERHEAD = 1.2
VIABLE_MIN_BITS = 4.0
# (max_gb_inclusive, tier) ordered ascending; first match wins.
TIER_THRESHOLDS: list[tuple[float, HardwareTier]] = [
    (16.0, HardwareTier.LAPTOP),
    (32.0, HardwareTier.APPLE_HIGH_RAM),
    (48.0, HardwareTier.SINGLE_GPU),
    (180.0, HardwareTier.WORKSTATION),
]


def estimate_memory_gb(
    params_total: int | None,
    bits_per_weight: float,
    context: int,
    num_layers: int | None,
    hidden_size: int | None,
) -> float | None:
    """Estimated RAM/VRAM (GB) to run the model at ``context`` tokens.

    Weights term always applies. KV-cache term is added only when architecture
    (layers + hidden size) is known; otherwise the estimate is weights-only.
    """
    if params_total is None:
        return None
    weights_gb = params_total * bits_per_weight / 8 / 1e9
    kv_cache_gb = 0.0
    if num_layers and hidden_size:
        # 2 (K and V) * 2 bytes (fp16) * layers * context * hidden.
        kv_cache_gb = 2 * 2 * num_layers * context * hidden_size / 1e9
    return round((weights_gb + kv_cache_gb) * OVERHEAD, 1)


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
    return HardwareTier.DATACENTER
