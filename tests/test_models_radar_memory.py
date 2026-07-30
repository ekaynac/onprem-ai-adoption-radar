from __future__ import annotations

from radar.models_radar.entities import (
    ArchitectureSpec,
    AttentionKind,
    HardwareTier,
    QuantVariant,
)
from radar.models_radar.memory import (
    estimate_memory_gb,
    hardware_tier,
    minimum_viable_quant,
)


def test_weights_only_when_arch_unknown():
    # v2: no architecture and no num_layers/hidden_size -> KV unmodelable (0.0).
    # weights = 8B * 4.5 bits / 8 / 1e9 = 4.5 GB.
    # 4.5 * FRAGMENTATION(1.05) + RUNTIME_BASELINE_GB(1.5) = 4.725 + 1.5 = 6.225
    # -> rounds to 6.23 (band [5.9, 6.6] covers either 6.22 or 6.23 rounding).
    gb = estimate_memory_gb(8_000_000_000, 4.5, context=4096, num_layers=None, hidden_size=None)
    assert 5.9 <= gb <= 6.6


def test_kv_cache_grows_with_context():
    small = estimate_memory_gb(8_000_000_000, 4.5, 4096, num_layers=32, hidden_size=4096)
    big = estimate_memory_gb(8_000_000_000, 4.5, 32768, num_layers=32, hidden_size=4096)
    assert big > small


def test_moe_uses_total_params_for_memory():
    # 30B total drives memory even though only 3B active.
    # v2: weights = 30e9*4.5/8/1e9 = 16.875 GB; *1.05 + 1.5 (no arch/KV) = 19.22 GB.
    gb = estimate_memory_gb(30_000_000_000, 4.5, 4096, num_layers=None, hidden_size=None)
    assert gb > 15  # ~19.22 GB weights-only; far above a 3B model's ~1.7 GB


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
    assert hardware_tier(150) == HardwareTier.SINGLE_GPU_DC   # was workstation
    assert hardware_tier(163) == HardwareTier.SINGLE_GPU_DC
    assert hardware_tier(400) == HardwareTier.SINGLE_NODE     # was datacenter
    assert hardware_tier(950) == HardwareTier.SINGLE_NODE
    assert hardware_tier(1000) == HardwareTier.MULTI_NODE
    assert hardware_tier(None) == HardwareTier.UNKNOWN


def test_mla_model_32k_estimate_is_sane_not_terabytes():
    # DeepSeek-V3/R1 class (671B, 61 layers, hidden_size 7168): the legacy
    # hidden_size-only MHA bound this formula used before MLA support gives KV
    # = 2*2*61*32768*7168/1e9 ~= 57.3 GB (total ~= (671+57.3)*1.2 ~= 874 GB) —
    # already wrong for a compressed-latent-cache model, and architectures with
    # larger per-head dims than "hidden_size/heads" push that upper bound much
    # higher still. v2 with MLA architecture computes the real latent-cache KV:
    # bytes/token = (kv_lora_rank=512 + qk_rope_head_dim=64) * 2 bytes * 61 layers
    #             = 70272 bytes/token
    # kv_gb at 32768 tokens = 70272*32768/1e9 = 2.3 GB (rounded).
    # 671*1.05 + 2.3 + 1.5 = 708.35 -- NOT 1000+.
    arch = ArchitectureSpec(attention_kind=AttentionKind.MLA, kv_lora_rank=512,
                            qk_rope_head_dim=64, num_key_value_heads=128,
                            num_attention_heads=128)
    gb = estimate_memory_gb(671_000_000_000, 8.0, 32768, 61, 7168, architecture=arch)
    assert 700 <= gb <= 715  # 671*1.05 + 2.3 + 1.5 = 708.35 -- NOT 1000+
