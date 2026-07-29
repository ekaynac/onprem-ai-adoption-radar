"""Architecture-correct KV math — the headline fix of the capacity engine."""

from __future__ import annotations

import pytest

from radar.capacity.kv import kv_bytes_per_token, kv_gb
from radar.models_radar.entities import ArchitectureSpec, AttentionKind


MLA_V3 = ArchitectureSpec(attention_kind=AttentionKind.MLA, num_attention_heads=128,
                          num_key_value_heads=128, kv_lora_rank=512, qk_rope_head_dim=64)
GQA_70B = ArchitectureSpec(attention_kind=AttentionKind.GQA, num_attention_heads=64,
                           num_key_value_heads=8, head_dim=128)
HYBRID_V4 = ArchitectureSpec(attention_kind=AttentionKind.HYBRID, num_attention_heads=128,
                             num_key_value_heads=1, head_dim=512, qk_rope_head_dim=64,
                             sliding_window=128)


def test_mla_golden_deepseek_v3():
    bpt, notes = kv_bytes_per_token(MLA_V3, num_layers=61, hidden_size=7168, kv_dtype="fp16")
    assert bpt == (512 + 64) * 2 * 61  # 70,272 bytes/token
    assert kv_gb(bpt, 32768) == pytest.approx(2.30, abs=0.01)
    assert kv_gb(bpt, 131072) == pytest.approx(9.21, abs=0.01)
    assert any("MLA" in n for n in notes)


def test_mla_fp8_halves():
    bpt16, _ = kv_bytes_per_token(MLA_V3, num_layers=61, hidden_size=7168, kv_dtype="fp16")
    bpt8, _ = kv_bytes_per_token(MLA_V3, num_layers=61, hidden_size=7168, kv_dtype="fp8")
    assert bpt8 == bpt16 / 2


def test_gqa_golden_llama70b_class():
    bpt, _ = kv_bytes_per_token(GQA_70B, num_layers=80, hidden_size=8192, kv_dtype="fp16")
    assert bpt == 2 * 8 * 128 * 2 * 80  # 327,680
    assert kv_gb(bpt, 32768) == pytest.approx(10.74, abs=0.01)


def test_hybrid_uses_gqa_upper_bound_and_flags_it():
    bpt, notes = kv_bytes_per_token(HYBRID_V4, num_layers=61, hidden_size=7168, kv_dtype="fp16")
    assert bpt == 2 * 1 * 512 * 2 * 61  # 124,928
    assert any("upper bound" in n for n in notes)


def test_legacy_mha_fallback_without_architecture():
    bpt, notes = kv_bytes_per_token(None, num_layers=32, hidden_size=4096, kv_dtype="fp16")
    assert bpt == 2 * 4096 * 2 * 32
    assert any("MHA upper bound" in n for n in notes)


def test_nothing_known_returns_none_with_reason():
    bpt, notes = kv_bytes_per_token(None, num_layers=None, hidden_size=None)
    assert bpt is None
    assert any("not modeled" in n for n in notes)


def test_concurrency_scales_linearly_and_dtype_validated():
    bpt, _ = kv_bytes_per_token(MLA_V3, num_layers=61, hidden_size=7168)
    assert kv_gb(bpt, 4096, concurrent_requests=200) == pytest.approx(
        kv_gb(bpt, 4096) * 200, rel=0.01)
    with pytest.raises(ValueError, match="fp16"):
        kv_bytes_per_token(MLA_V3, num_layers=61, hidden_size=7168, kv_dtype="fp3")
