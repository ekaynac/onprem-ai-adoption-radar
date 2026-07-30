"""Shared ArchitectureSpec fixtures for capacity-engine tests (sub-project D).

Used by test_capacity_kv.py and test_capacity_memory.py so the same golden
model shapes (MLA/GQA/HYBRID) back both the KV-math tests and the per-rank
memory/sharding tests.
"""

from __future__ import annotations

from radar.models_radar.entities import ArchitectureSpec, AttentionKind


MLA_V3 = ArchitectureSpec(attention_kind=AttentionKind.MLA, num_attention_heads=128,
                          num_key_value_heads=128, kv_lora_rank=512, qk_rope_head_dim=64)
GQA_70B = ArchitectureSpec(attention_kind=AttentionKind.GQA, num_attention_heads=64,
                           num_key_value_heads=8, head_dim=128)
HYBRID_V4 = ArchitectureSpec(attention_kind=AttentionKind.HYBRID, num_attention_heads=128,
                             num_key_value_heads=1, head_dim=512, qk_rope_head_dim=64,
                             sliding_window=128)
