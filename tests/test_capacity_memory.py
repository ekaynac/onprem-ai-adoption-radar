"""Per-rank memory accounting + TP/PP/EP sharding feasibility."""

from __future__ import annotations

import pydantic
import pytest

from capacity_fixtures import GQA_70B, HYBRID_V4, MLA_V3
from radar.capacity.memory import InfeasibleError, check_sharding, plan_memory
from radar.capacity.types import Parallelism, Workload
from radar.models_radar.devices import resolve_device


def test_parallelism_rejects_non_positive_fields():
    # tensor_parallel/pipeline_parallel/expert_parallel=0 (or negative) fed
    # straight into the solver's world_size division used to be an
    # uncaught ZeroDivisionError or silent negative-memory nonsense; each
    # field now has Field(ge=1) so pydantic rejects it at construction.
    for field in ("tensor_parallel", "pipeline_parallel", "expert_parallel"):
        with pytest.raises(pydantic.ValidationError):
            Parallelism(**{field: 0})
        with pytest.raises(pydantic.ValidationError):
            Parallelism(**{field: -2})


def test_v4_pro_fp8_tp16_fits_h200_rank():
    # 1600 GB weights / 16 ranks = 100 GB; KV 32k x 200 users fp8 hybrid-GQA:
    # 124928/2 B/token x32768 x200 /1e9 = 409.36 GB /(tp16 x pp1) = 25.585 GB
    # rank: 100 + 25.585 + 1.5 + 0.05x125.585 = 133.36 > 119.85 -> does NOT fit at 200 users
    plan = plan_memory(params_total=1_600_000_000_000, bits_per_weight=8.0,
                       architecture=HYBRID_V4, num_layers=61, hidden_size=7168,
                       workload=Workload(concurrent_requests=200, avg_context_tokens=32768),
                       parallelism=Parallelism(tensor_parallel=16),
                       device=resolve_device("h200-141gb"), kv_dtype="fp8")
    assert plan.per_rank.weights_gb == pytest.approx(100.0)
    assert plan.fits is False  # 200 concurrent at 32k needs more than 16 GPUs' memory
    # at 50 users it fits:
    plan50 = plan_memory(params_total=1_600_000_000_000, bits_per_weight=8.0,
                         architecture=HYBRID_V4, num_layers=61, hidden_size=7168,
                         workload=Workload(concurrent_requests=50, avg_context_tokens=32768),
                         parallelism=Parallelism(tensor_parallel=16),
                         device=resolve_device("h200-141gb"), kv_dtype="fp8")
    assert plan50.fits is True and plan50.headroom_fraction > 0


def test_sharding_infeasibility_reasons():
    problems = check_sharding(GQA_70B, num_layers=80,
                              parallelism=Parallelism(tensor_parallel=3))
    assert any("kv_heads" in p and "3" in p for p in problems)  # 8 % 3 != 0
    with pytest.raises(InfeasibleError) as exc:
        plan_memory(params_total=70_000_000_000, bits_per_weight=16.0,
                   architecture=GQA_70B, num_layers=80, hidden_size=8192,
                   workload=Workload(concurrent_requests=10, avg_context_tokens=4096),
                   parallelism=Parallelism(tensor_parallel=3),
                   device=resolve_device("h100-80gb"))
    assert exc.value.reasons


def test_mla_tp_exempt_from_kv_head_divisibility():
    assert check_sharding(MLA_V3, num_layers=61, parallelism=Parallelism(tensor_parallel=16)) == []


def test_kv_replication_disclosed_when_tp_exceeds_kv_heads():
    # HYBRID_V4 kv_heads=1, tp=16: tp far exceeds kv_heads -> replication note required.
    plan = plan_memory(params_total=1_600_000_000_000, bits_per_weight=8.0,
                       architecture=HYBRID_V4, num_layers=61, hidden_size=7168,
                       workload=Workload(concurrent_requests=50, avg_context_tokens=32768),
                       parallelism=Parallelism(tensor_parallel=16),
                       device=resolve_device("h200-141gb"), kv_dtype="fp8")
    assert any(
        "tensor_parallel" in note and "replicates KV" in note
        for note in plan.assumptions.lines
    )
    # GQA_70B kv_heads=8, tp=8: kv_heads >= tp (divides evenly, no replication) -> no note.
    plan_even = plan_memory(params_total=70_000_000_000, bits_per_weight=16.0,
                            architecture=GQA_70B, num_layers=80, hidden_size=8192,
                            workload=Workload(concurrent_requests=10, avg_context_tokens=4096),
                            parallelism=Parallelism(tensor_parallel=8),
                            device=resolve_device("h100-80gb"))
    assert not any("replicates KV" in note for note in plan_even.assumptions.lines)


# --- ruling 2026-07-30: uneven pipeline stages replace strict PP divisibility ---
#
# vLLM/TensorRT-LLM support uneven pipeline stages in production (a 61-layer
# DeepSeek-class checkpoint is routinely served at pp=2 as 31+30). The old
# `num_layers % pp != 0` hard failure was a plan defect: it made any
# prime-ish `num_layers` (e.g. 61) sharding-infeasible for almost every
# candidate GPU count, forcing an all-or-nothing jump. Replaced with
# largest-stage modeling: `stage_fraction = ceil(num_layers/pp)/num_layers`.


def test_check_sharding_uneven_pp_no_longer_a_problem():
    # ruling: 61 layers over pp=2 used to fail (61 % 2 != 0); now it's fine —
    # check_sharding only requires a known layer count and pp <= num_layers.
    assert check_sharding(HYBRID_V4, num_layers=61,
                          parallelism=Parallelism(tensor_parallel=8, pipeline_parallel=2)) == []


def test_check_sharding_pp_requires_known_layer_count():
    problems = check_sharding(HYBRID_V4, num_layers=None,
                              parallelism=Parallelism(tensor_parallel=8, pipeline_parallel=2))
    assert any("layer count unknown" in p for p in problems)


def test_check_sharding_pp_cannot_exceed_num_layers():
    problems = check_sharding(HYBRID_V4, num_layers=3,
                              parallelism=Parallelism(tensor_parallel=8, pipeline_parallel=4))
    assert any("exceeds num_layers=3" in p for p in problems)


def test_pp_uneven_stage_matches_hand_derivation():
    # hf-deepseek-v4-pro shape (HYBRID_V4, 61 layers) at tp=8,pp=2 (16 GPUs),
    # FP8 (8 bits), 50 users @ 32768 ctx, kv_dtype=fp8 — the exact shape
    # anchor 1 of test_capacity_solver.py resolves to.
    # stage_fraction = ceil(61/2)/61 = 31/61.
    # weights/rank = 1600 GB * (31/61) / (tp=8 * ep=1) = 49600/488 = 101.6393 GB.
    # KV: bytes/token = 2*1*512*1(fp8)*61 = 62464; kv_gb(62464,32768,50) =
    # round(102.3410176, 2) = 102.34 GB total * (31/61) / tp=8 = 6.5011 GB/rank.
    # fragmentation = 0.05*(101.6393+6.5011) = 5.4070; total =
    # 101.6393+6.5011+1.5+5.4070 = 115.0475 GB <= 119.85 usable -> fits,
    # headroom = (119.85-115.0475)/119.85 = 0.04007.
    plan = plan_memory(params_total=1_600_000_000_000, bits_per_weight=8.0,
                       architecture=HYBRID_V4, num_layers=61, hidden_size=7168,
                       workload=Workload(concurrent_requests=50, avg_context_tokens=32768),
                       parallelism=Parallelism(tensor_parallel=8, pipeline_parallel=2),
                       device=resolve_device("h200-141gb"), kv_dtype="fp8")
    assert plan.per_rank.weights_gb == pytest.approx(101.6393, abs=1e-3)
    assert plan.per_rank.kv_gb == pytest.approx(6.5011, abs=1e-3)
    assert plan.per_rank.total_gb == pytest.approx(115.0475, abs=1e-3)
    assert plan.fits is True
    assert plan.headroom_fraction == pytest.approx(0.04007, abs=1e-3)
    assert any("pipeline stages uneven: largest stage 31/61" in note
              for note in plan.assumptions.lines)
    # at tp=8,pp=1 (8 GPUs) it does NOT fit: weights/rank alone = 1600/8 = 200 GB.
    plan8 = plan_memory(params_total=1_600_000_000_000, bits_per_weight=8.0,
                        architecture=HYBRID_V4, num_layers=61, hidden_size=7168,
                        workload=Workload(concurrent_requests=50, avg_context_tokens=32768),
                        parallelism=Parallelism(tensor_parallel=8, pipeline_parallel=1),
                        device=resolve_device("h200-141gb"), kv_dtype="fp8")
    assert plan8.per_rank.weights_gb == pytest.approx(200.0)
    assert plan8.fits is False


def test_pp_stage_fraction_collapses_to_pre_ruling_math_invariant():
    """When pp==1, or layers split evenly, the new largest-stage formula must
    produce IDENTICAL numbers to the pre-ruling `weights_gb/world_size` and
    `kv_total/(tp*pp)` division — the ruling changes behavior only for
    genuinely uneven splits."""
    kwargs = dict(params_total=70_000_000_000, bits_per_weight=16.0,
                 architecture=GQA_70B, num_layers=80, hidden_size=8192,
                 workload=Workload(concurrent_requests=10, avg_context_tokens=4096),
                 device=resolve_device("h100-80gb"))
    # pp == 1: stage_fraction collapses to 1.0 -> weights/rank = weights_gb/tp.
    plan_pp1 = plan_memory(parallelism=Parallelism(tensor_parallel=8, pipeline_parallel=1), **kwargs)
    weights_gb_total = 70_000_000_000 * 16.0 / 8 / 1e9
    assert plan_pp1.per_rank.weights_gb == pytest.approx(weights_gb_total / 8)
    # 80 layers over pp=4 divides evenly (20 each) -> stage_fraction = 1/4,
    # identical to the old world_size=(tp*pp) division.
    plan_even = plan_memory(parallelism=Parallelism(tensor_parallel=8, pipeline_parallel=4), **kwargs)
    assert plan_even.per_rank.weights_gb == pytest.approx(weights_gb_total / (8 * 4))
    assert not any("uneven" in note for note in plan_even.assumptions.lines)
