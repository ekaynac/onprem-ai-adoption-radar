"""Per-rank memory accounting + TP/PP/EP sharding feasibility."""

from __future__ import annotations

import pytest

from capacity_fixtures import GQA_70B, HYBRID_V4, MLA_V3
from radar.capacity.memory import InfeasibleError, check_sharding, plan_memory
from radar.capacity.types import Parallelism, Workload
from radar.models_radar.devices import resolve_device


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
