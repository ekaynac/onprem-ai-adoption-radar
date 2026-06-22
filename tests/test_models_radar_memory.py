from __future__ import annotations

from radar.models_radar.entities import HardwareTier, QuantVariant
from radar.models_radar.memory import (
    estimate_memory_gb,
    hardware_tier,
    minimum_viable_quant,
)


def test_weights_only_when_arch_unknown():
    # 8B params at 4.5 bits ≈ 4.5 GB weights * 1.2 overhead ≈ 5.4 GB.
    gb = estimate_memory_gb(8_000_000_000, 4.5, context=4096, num_layers=None, hidden_size=None)
    assert 5.0 <= gb <= 5.8


def test_kv_cache_grows_with_context():
    small = estimate_memory_gb(8_000_000_000, 4.5, 4096, num_layers=32, hidden_size=4096)
    big = estimate_memory_gb(8_000_000_000, 4.5, 32768, num_layers=32, hidden_size=4096)
    assert big > small


def test_moe_uses_total_params_for_memory():
    # 30B total drives memory even though only 3B active.
    gb = estimate_memory_gb(30_000_000_000, 4.5, 4096, num_layers=None, hidden_size=None)
    assert gb > 15  # ~16.2 GB weights-only; far above a 3B model's ~1.7 GB


def test_estimate_none_without_params():
    assert estimate_memory_gb(None, 4.5, 4096, None, None) is None


def test_minimum_viable_quant_skips_sub_4bit():
    quants = [
        QuantVariant(format="Q2_K", bits_per_weight=2.6, est_memory_gb_4k=3.0),
        QuantVariant(format="Q4_K_M", bits_per_weight=4.5, est_memory_gb_4k=5.4),
        QuantVariant(format="Q8_0", bits_per_weight=8.0, est_memory_gb_4k=9.0),
    ]
    mv = minimum_viable_quant(quants)
    assert mv is not None and mv.format == "Q4_K_M"  # Q2 skipped, Q4 is the smallest viable


def test_minimum_viable_quant_none_when_no_estimates():
    assert minimum_viable_quant([QuantVariant(format="Q4_K_M", bits_per_weight=4.5)]) is None


def test_hardware_tier_boundaries():
    assert hardware_tier(12) == HardwareTier.LAPTOP
    assert hardware_tier(16) == HardwareTier.LAPTOP
    assert hardware_tier(24) == HardwareTier.APPLE_HIGH_RAM
    assert hardware_tier(48) == HardwareTier.SINGLE_GPU
    assert hardware_tier(120) == HardwareTier.WORKSTATION
    assert hardware_tier(400) == HardwareTier.DATACENTER
    assert hardware_tier(None) == HardwareTier.UNKNOWN
