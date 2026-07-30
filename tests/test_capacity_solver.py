"""The capacity solver's anchor cases — GPU counts from workloads, workloads
from fleets (spec §6, sub-project D, task 5).

Every arithmetic-bearing assertion below is hand-derived in a comment from
the real constants (weights/rank, ``kv_gb`` rounding, 5% fragmentation,
1.5 GB baseline, 119.85 GB usable/H200-GPU) before being pinned — per the
task's anchor-verification duty.

Ruling 2026-07-30: the two ``hf-deepseek-v4-pro`` anchors originally
deviated from the brief because ``num_layers=61`` is prime and
``memory.check_sharding`` used to require the pipeline-parallel split to
divide the layer count evenly — an all-or-nothing jump (1 node, or exactly
61 nodes) that real engines don't actually have (vLLM/TensorRT-LLM serve
uneven pipeline stages routinely). That rule was adjudicated a plan defect
and replaced with largest-stage modeling in ``radar.capacity.memory``
(``stage_fraction = ceil(num_layers/pp)/num_layers``). Both anchors are
restored to the brief's original numbers below, re-derived under the new
math.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from radar.capacity.memory import InfeasibleError
from radar.capacity.solver import _candidate_counts, _layout_for_count, max_workload, plan_capacity
from radar.capacity.types import Workload
from radar.models_radar.assemble import build_model_entry
from radar.models_radar.devices import resolve_device
from radar.models_radar.entities import ModelEntry, QuantVariant
from radar.models_radar.seed import load_model_seed


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _entry(seed_id: str) -> ModelEntry:
    # build via load_model_seed + build_model_entry(seed, None, []) — offline, deterministic
    seeds = {s.id: s for s in load_model_seed(_REPO_ROOT / "config" / "model-seed.yaml")}
    return build_model_entry(seeds[seed_id], None, [])


def test_anchor_v4_pro_needs_two_h200_nodes_for_50_users():
    # hf-deepseek-v4-pro: num_layers=61, FP8 fallback (no catalog "FP8" —
    # offline build synthesizes a GGUF-only ladder) -> bits=8.0.
    # count=8 (tp=8,pp=1): weights/rank = 1600 GB / 8 = 200 GB >> 119.85
    # usable -> doesn't fit (pp=1 never invokes stage_fraction, so this is
    # unaffected by the ruling).
    # count=16 (tp=8,pp=2): under the ruling, pp=2 no longer needs to divide
    # 61 evenly — largest stage = ceil(61/2) = 31 layers, stage_fraction =
    # 31/61.
    #   weights/rank = 1600 * (31/61) / (tp=8 * ep=1) = 49600/488 = 101.6393 GB
    #   KV (hybrid, kv_heads=1, head_dim=512, fp8=1 byte, 61 layers):
    #   bytes/token = 2*1*512*1*61 = 62464; kv_gb(62464,32768,50) =
    #   round(62464*32768*50/1e9, 2) = round(102.3410176, 2) = 102.34 GB
    #   total * (31/61) / tp=8 = 6.5011 GB/rank.
    #   fragmentation = 0.05*(101.6393+6.5011) = 5.4070
    #   total = 101.6393+6.5011+1.5+5.4070 = 115.0475 GB <= 119.85 usable
    #   -> FITS, headroom = (119.85-115.0475)/119.85 = 0.04007 > 0.
    # count=16 is the first fit (count=8 didn't), matching the brief exactly.
    # Confirmed by direct execution (see tests/test_capacity_memory.py's
    # test_pp_uneven_stage_matches_hand_derivation for the same numbers
    # pinned at the memory layer directly).
    plan = plan_capacity(_entry("hf-deepseek-v4-pro"), "hgx-h200-8",
                         Workload(concurrent_requests=50, avg_context_tokens=32768),
                         quant_format="FP8", kv_dtype="fp8")
    assert plan.n_gpus == 16 and plan.n_nodes == 2
    assert plan.memory.fits and plan.memory.headroom_fraction > 0
    assert plan.throughput is not None and plan.throughput.per_user_decode_tps > 30
    assert any("quant FP8 not in catalog" in line for line in plan.assumptions.lines)
    assert any("pipeline stages uneven: largest stage 31/61" in line
              for line in plan.assumptions.lines)


def test_anchor_v4_pro_wont_fit_single_h200_and_says_why():
    # Intent: "one H200 cannot hold V4-Pro." plan_capacity is a search — by
    # design it escalates GPU count until something fits (it found n_gpus=16
    # above), so it can never itself demonstrate "doesn't fit on hardware of
    # this class" the way a FIXED-fleet-size query can. max_workload with
    # n_gpus=1 pins the fleet size and asks the direct question instead:
    # tp=1,pp=1,world_size=1 -> weights/rank = 1600 GB/1 = 1600 GB (FP8
    # fallback) >> 119.85 GB usable even before any concurrency is added
    # (B=1) -> InfeasibleError with a "memory shortfall" reason.
    with pytest.raises(InfeasibleError) as exc:
        max_workload(_entry("hf-deepseek-v4-pro"), "h200-141gb", 1,
                     avg_context_tokens=4096, quant_format="FP8")
    assert any("memory" in r.lower() for r in exc.value.reasons)

    # And plan_capacity on the SAME device confirms the "no single H200"
    # finding from the other direction: it must escalate to at least 16 GPUs
    # (2 nodes' worth) before anything fits — never settling for 1, 2, 4, or 8.
    plan = plan_capacity(_entry("hf-deepseek-v4-pro"), "h200-141gb",
                         Workload(concurrent_requests=1, avg_context_tokens=4096),
                         quant_format="FP8")
    assert plan.n_gpus >= 16


def test_anchor_deepseek_v3_fits_one_h200_node_fp8():
    # deepseek-v3: num_layers=61 too, but MLA (kv_lora_rank=512) means
    # count=8 (tp=8,pp=1) never needs pp>1, so the ruling doesn't move this
    # number at all. FP8 fallback (no catalog "FP8"): bits=8.0.
    # weights_gb = 671e9*8/8/1e9 = 671 GB total /8 = 83.875 GB/rank.
    # KV (MLA, kv_lora_rank=512, qk_rope_head_dim=64, fp8 1 byte, 61 layers):
    # bytes/token = (512+64)*1*61 = 35136; kv_gb(35136,32768,20) =
    # round(35136*32768*20/1e9, 2) = 23.03 GB total /(tp*pp=8) = 2.87875 GB/rank
    # (~2.88). fragmentation = 0.05*(83.875+2.87875) = 4.3376875; total =
    # 83.875+2.87875+1.5+4.3376875 = 92.5914375 GB (~92.59) <= 119.85 usable
    # -> fits at n_gpus=8, comfortably under the 119.85 GB/GPU ceiling.
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
    # 61 layers): bytes/token = (512+64)*1*61 = 35136 (576 bytes/layer * 61
    # layers, NOT 576 alone) -> 35136 bytes/token * 32768 = 1.151 GB/request
    # (matches the ambiguity note "~250 GB KV headroom / 1.15 GB per user").
    # So max B ~ 230.7/1.151 ~= 200 — comfortably >= 50.
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
    # A synthetic 100T-param model with a KNOWN num_layers=64 (chosen so
    # pipeline_parallel, which tops out at count//8=64 for candidates up to
    # 512, never exceeds it — check_sharding's new "pp > num_layers" rule
    # would otherwise start rejecting candidates on layer-count grounds
    # rather than memory grounds, muddying this test's intent). Every
    # candidate up to 512 GPUs is sharding-feasible; none fit on memory.
    # At 512 GPUs (tp=8,pp=64,ep=1): stage_fraction = ceil(64/64)/64 = 1/64;
    # weights/rank = 100e12*8/8/1e9 * (1/64) / 8 = 100000/512 = 195.3125 GB;
    # + 5% fragmentation (9.766) + 1.5 baseline = 206.58 GB, still >> 119.85
    # GB usable -> genuinely infeasible everywhere (confirmed by direct
    # execution: last reason is at n_gpus=512, "memory shortfall").
    huge = ModelEntry(
        id="synthetic-huge", name="Synthetic Huge", family="synthetic",
        params_total=100_000_000_000_000, num_layers=64,
        quants=[QuantVariant(format="FP8", bits_per_weight=8.0)],
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
    assert any("memory" in r.lower() for r in exc.value.reasons)


def test_max_workload_raises_when_pp_exceeds_num_layers():
    # ruling 2026-07-30: check_sharding's PP rule is no longer "must divide
    # evenly" but IS still "pp <= num_layers" (can't have more pipeline
    # stages than layers to put in them). A synthetic 3-layer toy model at
    # n_gpus=32 forces pp=4 (32//8), which exceeds num_layers=3.
    tiny = ModelEntry(id="tiny-3-layer", name="tiny", family="synthetic",
                     params_total=1_000_000_000, num_layers=3,
                     quants=[QuantVariant(format="FP8", bits_per_weight=8.0)])
    with pytest.raises(InfeasibleError) as exc:
        max_workload(tiny, "hgx-h200-8", 32, avg_context_tokens=1024, quant_format="FP8")
    assert any("exceeds num_layers=3" in r for r in exc.value.reasons)


def test_max_workload_raises_when_layer_count_unknown_for_pp():
    # ruling 2026-07-30: pp > 1 with an unknown layer count can't be sized
    # at all (no way to know the largest stage), so it's still rejected —
    # just with a different, more honest reason than "doesn't divide evenly".
    unknown_layers = ModelEntry(id="unknown-layers", name="unknown", family="synthetic",
                               params_total=1_000_000_000, num_layers=None,
                               quants=[QuantVariant(format="FP8", bits_per_weight=8.0)])
    with pytest.raises(InfeasibleError) as exc:
        max_workload(unknown_layers, "hgx-h200-8", 16, avg_context_tokens=1024, quant_format="FP8")
    assert any("layer count unknown" in r for r in exc.value.reasons)


# --- final-review fixes: input guards + no phantom-GPU throughput --------


def test_max_workload_rejects_non_positive_n_gpus():
    # A fleet needs at least one GPU; 0 used to raise a raw ZeroDivisionError
    # (division by world_size inside the memory/throughput math), negative
    # values used to silently produce nonsense "fits" plans. Both now raise a
    # readable ValueError up front, which folds into the CLI's/MCP's existing
    # ValueError handling instead of a traceback.
    with pytest.raises(ValueError, match="n_gpus must be >= 1"):
        max_workload(_entry("deepseek-v3"), "hgx-h200-8", 0, avg_context_tokens=32768)
    with pytest.raises(ValueError, match="n_gpus must be >= 1"):
        max_workload(_entry("deepseek-v3"), "hgx-h200-8", -4, avg_context_tokens=32768)


def test_max_workload_gpus_12_uses_world_size_not_phantom_bandwidth():
    # _layout_for_count(12) = TP8/PP1 -> world_size=8: PP only advances in
    # whole 8-GPU stages, so 12 collapses to the same reachable layout as 8 —
    # 4 of the 12 requested GPUs are never addressed by it. Both the memory
    # plan and the throughput estimate must be solved at world_size (never
    # the phantom 12), so --gpus 12 must report the SAME per-user t/s as
    # --gpus 8 (not ~50% more from invented bandwidth), plus an idle-GPU note
    # that --gpus 8 does not carry.
    mw8 = max_workload(_entry("deepseek-v3"), "hgx-h200-8", 8,
                       avg_context_tokens=32768, quant_format="FP8", kv_dtype="fp8")
    mw12 = max_workload(_entry("deepseek-v3"), "hgx-h200-8", 12,
                        avg_context_tokens=32768, quant_format="FP8", kv_dtype="fp8")
    assert mw12.n_gpus == 12  # still reports the fleet size actually asked about
    assert mw12.max_concurrent_at_context == mw8.max_concurrent_at_context
    assert mw12.per_user_decode_tps_at_max == mw8.per_user_decode_tps_at_max
    assert any("layout uses 8 of 12 GPUs" in line and "4 GPU(s) idle" in line
              for line in mw12.assumptions.lines)
    assert not any("idle" in line for line in mw8.assumptions.lines)


def test_candidate_counts_include_unreachable_layouts_that_plan_capacity_must_skip():
    # A device.gpu_count that isn't itself a multiple of 8 generates candidate
    # counts (10, 12, 14, ...) whose pinned layout (TP<=8, PP in whole 8-GPU
    # stages) can't express them -- they collapse to the SAME world_size as a
    # smaller candidate already tried (e.g. _layout_for_count(12).world_size
    # == 8, same as count=8). This pins the exact set plan_capacity's
    # world_size != count skip must reject for such a device.
    device = resolve_device({"kind": "gpu", "total_memory_gb": 141, "gpu_count": 2})
    counts = _candidate_counts(device)[:8]
    assert counts == [2, 4, 6, 8, 10, 12, 14, 16]
    unreachable = [c for c in counts if _layout_for_count(c).world_size != c]
    assert unreachable == [10, 12, 14]  # 16 is a real TP8/PP2 layout again


def test_plan_capacity_never_returns_a_phantom_gpu_layout():
    # spec property: a returned plan's layout must actually use every GPU it
    # reports -- world_size (tp*pp*ep) must equal n_gpus, never an inflated
    # count the layout heuristic can't express. Checked over the existing
    # anchor scenarios (their device presets all have gpu_count a multiple
    # of 8, so the invariant already held for them; pinning it here catches
    # any future preset/heuristic change that would break it).
    scenarios = [
        ("hf-deepseek-v4-pro", "hgx-h200-8",
         Workload(concurrent_requests=50, avg_context_tokens=32768), "FP8", "fp8"),
        ("deepseek-v3", "hgx-h200-8",
         Workload(concurrent_requests=20, avg_context_tokens=32768), "FP8", "fp8"),
        ("hf-glm-5-2", "hgx-h200-8",
         Workload(concurrent_requests=10, avg_context_tokens=16384), "FP8", "fp8"),
    ]
    for model_id, device_id, workload, quant, kv_dtype in scenarios:
        plan = plan_capacity(_entry(model_id), device_id, workload,
                             quant_format=quant, kv_dtype=kv_dtype)
        assert plan.parallelism.world_size == plan.n_gpus
