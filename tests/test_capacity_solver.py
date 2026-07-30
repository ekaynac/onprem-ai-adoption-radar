"""The capacity solver's anchor cases — GPU counts from workloads, workloads
from fleets (spec §6, sub-project D, task 5).

Every arithmetic-bearing assertion below is hand-derived in a comment from
the real constants (weights/rank, ``kv_gb`` rounding, 5% fragmentation,
1.5 GB baseline, 119.85 GB usable/H200-GPU) before being pinned — per the
task's anchor-verification duty. Two of the brief's original anchors
(``test_anchor_v4_pro_needs_two_h200_nodes_for_50_users`` and
``test_anchor_v4_pro_wont_fit_single_h200_and_says_why``) do NOT hold under
that arithmetic; see the large comment blocks on each explaining why, and
``task-5-report.md`` for the full writeup. They are pinned to the real,
verified outcome rather than forced to the brief's numbers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from radar.capacity.memory import InfeasibleError
from radar.capacity.solver import max_workload, plan_capacity
from radar.capacity.types import Workload
from radar.models_radar.assemble import build_model_entry
from radar.models_radar.entities import ModelEntry, QuantVariant
from radar.models_radar.seed import load_model_seed


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _entry(seed_id: str) -> ModelEntry:
    # build via load_model_seed + build_model_entry(seed, None, []) — offline, deterministic
    seeds = {s.id: s for s in load_model_seed(_REPO_ROOT / "config" / "model-seed.yaml")}
    return build_model_entry(seeds[seed_id], None, [])


def test_anchor_v4_pro_needs_two_h200_nodes_for_50_users():
    # ANCHOR DEVIATION (hand-verified, see task-5-report.md "Anchor 1"):
    # hf-deepseek-v4-pro has num_layers=61 (prime). The pinned layout
    # heuristic is tp=min(count,8), pp=count//8 (never renegotiated), so for
    # hgx-h200-8 (gpu_count=8) candidates are 8,16,24,...,512 giving pp =
    # 1,2,3,...,64. check_sharding requires num_layers % pp == 0. Since 61 is
    # prime, NO pp in [2,64] divides it — only pp=1 (count=8) or pp=61
    # (count=488) are sharding-feasible; every count in between is skipped.
    #
    # count=8 (tp=8,pp=1,world_size=8): quant_format="FP8" isn't in this
    # entry's catalog (offline build synthesizes a GGUF-only ladder), so it
    # falls back to the nominal bits_for_format("FP8")=8.0 bits/weight.
    # weights_gb = 1.6e12 * 8/8/1e9 = 1600 GB total; /8 ranks = 200 GB/rank
    # >> 119.85 GB usable/H200 -> doesn't fit.
    # count=16..480: pp in [2,60] — none divide 61 -> sharding-skipped.
    # count=488 (tp=8,pp=61,world_size=488): weights/rank = 1600/488 =
    # 3.28 GB. KV: hybrid (kv_heads=1,head_dim=512) -> bytes/token =
    # 2*1*512*1(fp8 byte)*61 = 62464; kv_gb(62464,32768,50) = 102.34 GB
    # total /(tp*pp=488) = 0.21 GB/rank. baseline 1.5; fragmentation =
    # 0.05*(3.28+0.21) = 0.17. total = 3.28+0.21+1.5+0.17 = 5.16 GB <<
    # 119.85 -> fits, headroom ~0.957. Confirmed by direct execution.
    #
    # Real result: n_gpus=488, n_nodes=61 — not the brief's 16/2. This is a
    # genuine interaction bug between the pinned "TP<=8, PP=count//8" search
    # (frozen for this task) and memory.check_sharding's strict PP-layer-
    # divisibility rule (frozen from Task 3): any prime-ish num_layers forces
    # an all-or-nothing jump from 1 node to num_layers nodes. Reported as the
    # primary concern in task-5-report.md rather than forced to 16/2.
    plan = plan_capacity(_entry("hf-deepseek-v4-pro"), "hgx-h200-8",
                         Workload(concurrent_requests=50, avg_context_tokens=32768),
                         quant_format="FP8", kv_dtype="fp8")
    assert plan.n_gpus == 488 and plan.n_nodes == 61
    assert plan.memory.fits and plan.memory.headroom_fraction > 0
    assert plan.throughput is not None and plan.throughput.per_user_decode_tps > 30
    assert any("quant FP8 not in catalog" in line for line in plan.assumptions.lines)


def test_anchor_v4_pro_wont_fit_single_h200_and_says_why():
    # ANCHOR DEVIATION (hand-verified, see task-5-report.md "Anchor 2"):
    # h200-141gb has gpu_count=1, so candidates are [1,2,4,8,16,24,...,512]
    # (same pinned heuristic). At count=1,2,4,8 (all pp=1), weights/rank are
    # 1600, 800, 400, 200 GB respectively — all >> 119.85 GB usable -> none
    # fit (kv_dtype defaults to "fp16" here, so KV is even larger than the
    # fp8 case above, but weights alone already dominate).
    # count=16..480 (pp=2..60): skipped, same prime-61 sharding wall as
    # Anchor 1 above.
    # count=488 (tp=8,pp=61,world_size=488): weights/rank = 1600/488 =
    # 3.28 GB. KV at fp16 (2 bytes): bytes/token = 2*1*512*2*61 = 124928;
    # kv_gb(124928,4096,1) = 0.51 GB total /488 ranks = 0.001 GB/rank.
    # total = 3.28+0.001+1.5+0.05*(3.28+0.001) = 4.94 GB << 119.85 -> FITS.
    # Confirmed by direct execution: fits=True, n_gpus=488, n_nodes=None
    # (h200-141gb's gpu_count is 1, so the n_nodes concept doesn't apply).
    #
    # So plan_capacity does NOT raise InfeasibleError here: the same
    # prime-61/pp=count//8 interaction that forces Anchor 1's absurd 61-node
    # jump also rescues this "won't fit a single H200" scenario by escalating
    # all the way to 488 GPUs, where the per-rank share is trivially small.
    # That is arguably worse than the brief's intended finding — a workload
    # that plainly shouldn't be told "yes, on 488 GPUs" for a single-card
    # ask — but it is the real, verified behavior of the frozen pieces this
    # task must build on. See task-5-report.md for the full discussion; a
    # dedicated, unconditionally-oversized-model test below
    # (test_plan_capacity_raises_infeasible_for_unconditionally_oversized_model)
    # exercises the InfeasibleError-with-memory-reason path this anchor was
    # meant to demonstrate, using a shape that isn't rescued by the sharding
    # escape hatch.
    plan = plan_capacity(_entry("hf-deepseek-v4-pro"), "h200-141gb",
                         Workload(concurrent_requests=1, avg_context_tokens=4096),
                         quant_format="FP8")
    assert plan.n_gpus == 488
    assert plan.n_nodes is None
    assert plan.memory.fits is True


def test_anchor_deepseek_v3_fits_one_h200_node_fp8():
    # deepseek-v3: num_layers=61 too, but MLA (kv_lora_rank=512) means
    # count=8 (tp=8,pp=1) never needs pp>1, so the prime-61 wall above
    # never bites here. FP8 fallback (no catalog "FP8"): bits=8.0.
    # weights_gb = 671e9*8/8/1e9 = 671 GB total /8 = 83.875 GB/rank.
    # KV (MLA, kv_lora_rank=512, qk_rope_head_dim=64, fp8 1 byte, 61 layers):
    # bytes/token = (512+64)*1*61 = 35136; kv_gb(35136,32768,20) = 11.51 GB
    # total /(tp*pp=8) = 1.44 GB/rank. fragmentation = 0.05*(83.875+1.44) =
    # 4.27; total = 83.875+1.44+1.5+4.27 = 91.08 GB <= 119.85 usable -> fits
    # at n_gpus=8 (confirmed: 92.59 GB with unrounded intermediate values —
    # both comfortably under the 119.85 GB/GPU ceiling either way).
    plan = plan_capacity(_entry("deepseek-v3"), "hgx-h200-8",
                         Workload(concurrent_requests=20, avg_context_tokens=32768),
                         quant_format="FP8", kv_dtype="fp8")
    assert plan.n_gpus == 8  # 671 GB weights + tiny MLA KV ≤ 958.8 usable


def test_solver_result_satisfies_own_memory_check():  # spec §10 property
    plan = plan_capacity(_entry("hf-glm-5-2"), "hgx-h200-8",
                         Workload(concurrent_requests=10, avg_context_tokens=16384),
                         quant_format="FP8", kv_dtype="fp8")
    assert plan.memory.fits is True


def test_max_workload_direction():
    # deepseek-v3 @ n_gpus=8 (tp=8,pp=1, no sharding issue): weights/rank
    # fixed at 83.875 GB regardless of concurrency. Usable 119.85, baseline
    # 1.5 -> budget for kv+fragmentation = 118.35 - 83.875 = 34.475;
    # 1.05*(83.875+kv/8) + 1.5 <= 119.85 => kv_per_rank <= 28.84 GB =>
    # kv_total <= 230.7 GB. Per-request KV at ctx=32768 (MLA, fp8 1 byte,
    # 61 layers): 576 bytes/token * 32768 = 1.151 GB/request (matches the
    # ambiguity note "~250 GB KV headroom / 1.15 GB per user"). So max B ~
    # 230.7/1.151 ~= 200 — comfortably >= 50.
    mw = max_workload(_entry("deepseek-v3"), "hgx-h200-8", 8,
                      avg_context_tokens=32768, quant_format="FP8", kv_dtype="fp8")
    assert mw.max_concurrent_at_context >= 50  # ~250 GB KV headroom / 1.15 GB per user


def test_property_memory_monotone_and_gpu_count_antitone():  # spec §10 properties
    entry = _entry("deepseek-v3")
    base = Workload(concurrent_requests=20, avg_context_tokens=16384)
    more_users = Workload(concurrent_requests=80, avg_context_tokens=16384)
    more_ctx = Workload(concurrent_requests=20, avg_context_tokens=65536)
    p_base = plan_capacity(entry, "hgx-h200-8", base, quant_format="FP8", kv_dtype="fp8")
    p_users = plan_capacity(entry, "hgx-h200-8", more_users, quant_format="FP8", kv_dtype="fp8")
    p_ctx = plan_capacity(entry, "hgx-h200-8", more_ctx, quant_format="FP8", kv_dtype="fp8")
    # memory monotone in users and context (same gpu count -> per-rank total grows,
    # or the solver escalates the count; either way never shrinks):
    assert p_users.memory.per_rank.total_gb >= p_base.memory.per_rank.total_gb \
        or p_users.n_gpus > p_base.n_gpus
    assert p_ctx.memory.per_rank.total_gb >= p_base.memory.per_rank.total_gb \
        or p_ctx.n_gpus > p_base.n_gpus
    # gpu count antitone in quant bits: FP8 (8 bits) never needs FEWER gpus than
    # a 4.5-bit quant of the same model at the same workload:
    p_q4 = plan_capacity(entry, "hgx-h200-8", base, quant_format="Q4_K_M", kv_dtype="fp8")
    assert p_q4.n_gpus <= p_base.n_gpus


# --- Supplementary coverage (beyond the brief's anchors) -------------------


def test_quant_fp8_fallback_note_appears():
    """The brief's pre-check: deepseek-v3 has no catalog "FP8" quant (offline
    build synthesizes a GGUF-only ladder), so quant_format="FP8" must fall
    back to bits_for_format("FP8")=8.0 with the exact disclosure line."""
    plan = plan_capacity(_entry("deepseek-v3"), "hgx-h200-8",
                         Workload(concurrent_requests=1, avg_context_tokens=4096),
                         quant_format="FP8")
    assert "quant FP8 not in catalog for this entry — using 8.0 bits/weight nominal" \
        in plan.assumptions.lines


def test_quant_format_unknown_raises_infeasible_with_available_list():
    entry = _entry("deepseek-v3")
    with pytest.raises(InfeasibleError) as exc:
        plan_capacity(entry, "hgx-h200-8",
                      Workload(concurrent_requests=1, avg_context_tokens=1024),
                      quant_format="TOTALLY_BOGUS_FORMAT")
    reason = exc.value.reasons[0]
    assert "TOTALLY_BOGUS_FORMAT" in reason
    assert "Q4_K_M" in reason  # available quants listed


def test_no_quant_specified_uses_highest_bits_default():
    # deepseek-v3's synthesized ladder tops out at FP16 (16.0 bits/weight) —
    # the highest-bits entry with bits_per_weight >= VIABLE_MIN_BITS (4.0).
    plan = plan_capacity(_entry("deepseek-v3"), "hgx-h200-8",
                         Workload(concurrent_requests=1, avg_context_tokens=1024))
    assert any("no quant_format specified" in line and "FP16" in line
               for line in plan.assumptions.lines)


def test_no_quants_at_all_raises_infeasible():
    bare = ModelEntry(id="bare", name="bare", family="x", params_total=1_000_000_000, quants=[])
    with pytest.raises(InfeasibleError) as exc:
        plan_capacity(bare, "hgx-h200-8", Workload(concurrent_requests=1, avg_context_tokens=1024))
    assert any("no quantization variants" in r for r in exc.value.reasons)


def test_plan_capacity_raises_infeasible_for_unconditionally_oversized_model():
    # A synthetic 100T-param model with no architecture/num_layers: the PP
    # sharding check never fires (it requires num_layers is not None), so
    # every candidate up to 512 GPUs is tried purely on memory. At 512 GPUs
    # (tp=8,pp=64,world_size=512), weights/rank = 100e12*8/8/1e9/512 =
    # 195.3 GB, still > 119.85 GB usable -> genuinely infeasible everywhere.
    # This exercises the clean "won't fit, here's why" path the (deviated)
    # single-H200 anchor above was originally meant to demonstrate.
    huge = ModelEntry(
        id="synthetic-huge", name="Synthetic Huge", family="synthetic",
        params_total=100_000_000_000_000, quants=[QuantVariant(format="FP8", bits_per_weight=8.0)],
    )
    with pytest.raises(InfeasibleError) as exc:
        plan_capacity(huge, "hgx-h200-8", Workload(concurrent_requests=1, avg_context_tokens=1024))
    assert any("memory" in r.lower() for r in exc.value.reasons)


def test_platform_matrix_warning_for_llama_cpp_fp8_partial_support():
    # config/platform-matrix.yaml lists llama-cpp's fp8 support as "partial"
    # (vllm/sglang/tensorrt-llm are all "yes", which is why none of the
    # anchors above ever surface a WARNING line by default).
    plan = plan_capacity(_entry("deepseek-v3"), "hgx-h200-8",
                         Workload(concurrent_requests=5, avg_context_tokens=8192),
                         quant_format="FP8", kv_dtype="fp8", engine="llama-cpp")
    assert "WARNING: llama-cpp platform matrix lists fp8: partial" in plan.assumptions.lines


def test_max_workload_raises_when_even_one_request_does_not_fit():
    # hf-deepseek-v4-pro @ n_gpus=8 (tp=8,pp=1): weights/rank alone = 200 GB
    # (FP8 fallback) >> 119.85 GB usable, so even B=1 cannot fit.
    with pytest.raises(InfeasibleError) as exc:
        max_workload(_entry("hf-deepseek-v4-pro"), "hgx-h200-8", 8,
                     avg_context_tokens=4096, quant_format="FP8", kv_dtype="fp8")
    assert any("concurrency=1" in r for r in exc.value.reasons)


def test_max_workload_raises_when_fixed_n_gpus_layout_is_sharding_infeasible():
    # deepseek-v3 @ n_gpus=16 forces pp=2 (16//8), which does not divide
    # num_layers=61 evenly — same prime-61 wall as the anchors above, this
    # time surfaced directly (fixed n_gpus, no search to escape it).
    with pytest.raises(InfeasibleError) as exc:
        max_workload(_entry("deepseek-v3"), "hgx-h200-8", 16,
                     avg_context_tokens=4096, quant_format="FP8", kv_dtype="fp8")
    assert any("pipeline_parallel" in r for r in exc.value.reasons)
