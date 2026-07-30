"""Roofline throughput model — decode from memory bandwidth, prefill from TFLOPS."""

from __future__ import annotations

import pytest

from radar.capacity.throughput import (
    ENGINE_EFFICIENCY,
    estimate_throughput,
    weight_dtype_for_bits,
)
from radar.capacity.types import Workload
from radar.models_radar.devices import resolve_device


def test_v4_pro_decode_on_16x_h200_at_200_users():
    # active 49B fp8 = 49 GB/step weights; KV read 200x32768x62464 B = 409,364,070,400 B
    # bytes/step = 458,364,070,400 B (458.36 GB); agg bw = 16x4800e9x0.6 = 46.08e12 B/s
    # agg tps = 46.08e12 x 200 / 458,364,070,400 ~= 20,106.3 t/s -> per-user ~= 100.5 t/s
    est = estimate_throughput(params_active=49_000_000_000, params_total=1_600_000_000_000,
                              bits_per_weight=8.0, kv_bytes_per_token=124928 / 2,
                              workload=Workload(concurrent_requests=200, avg_context_tokens=32768),
                              device=resolve_device("h200-141gb"), n_gpus=16, engine="vllm")
    assert est is not None
    assert est.per_user_decode_tps == pytest.approx(100.5, rel=0.02)
    assert est.aggregate_decode_tps == pytest.approx(20106.3, rel=0.02)
    raw_prefill_tps = 16 * 1979e12 * 0.5 / (2 * 49e9)
    assert est.prefill_tps == pytest.approx(raw_prefill_tps, rel=0.01)
    # ttft is rounded to 2 decimals; at ~0.2s that rounding step is a few
    # percent relative, so compare against the raw (unrounded) formula with
    # an absolute tolerance sized to the rounding granularity, not rel=.
    assert est.ttft_seconds == pytest.approx(32768 / raw_prefill_tps, abs=0.01)
    assert any("0.6" in n or "0.60" in n for n in est.assumptions.lines)
    assert any("vllm" in n for n in est.assumptions.lines)
    assert any("active expert weights only" in n for n in est.assumptions.lines)


def test_no_bandwidth_returns_none():
    custom = resolve_device({"kind": "gpu", "total_memory_gb": 141, "gpu_count": 8})
    est = estimate_throughput(params_active=None, params_total=70_000_000_000,
                              bits_per_weight=8.0, kv_bytes_per_token=62464.0,
                              workload=Workload(concurrent_requests=10, avg_context_tokens=4096),
                              device=custom, n_gpus=8, engine="vllm")
    assert est is None


def test_batch_amortizes_weight_reads():
    device = resolve_device("h200-141gb")
    one = estimate_throughput(params_active=None, params_total=70_000_000_000,
                              bits_per_weight=8.0, kv_bytes_per_token=62464.0,
                              workload=Workload(concurrent_requests=1, avg_context_tokens=4096),
                              device=device, n_gpus=8, engine="vllm")
    many = estimate_throughput(params_active=None, params_total=70_000_000_000,
                               bits_per_weight=8.0, kv_bytes_per_token=62464.0,
                               workload=Workload(concurrent_requests=64, avg_context_tokens=4096),
                               device=device, n_gpus=8, engine="vllm")
    assert one is not None and many is not None
    assert many.aggregate_decode_tps > one.aggregate_decode_tps * 10  # batching wins
    assert many.per_user_decode_tps < one.per_user_decode_tps        # but per-user drops


def test_weight_dtype_for_bits_thresholds():
    assert weight_dtype_for_bits(16.0) == "fp16"
    assert weight_dtype_for_bits(12.0) == "fp16"
    assert weight_dtype_for_bits(8.0) == "fp8"
    assert weight_dtype_for_bits(6.0) == "fp8"
    assert weight_dtype_for_bits(4.0) == "fp4"
    assert weight_dtype_for_bits(1.0) == "fp4"


def test_unknown_engine_raises_with_known_engines_listed():
    with pytest.raises(ValueError, match="vllm") as exc:
        estimate_throughput(params_active=None, params_total=70_000_000_000,
                            bits_per_weight=8.0, kv_bytes_per_token=62464.0,
                            workload=Workload(concurrent_requests=1, avg_context_tokens=4096),
                            device=resolve_device("h200-141gb"), n_gpus=8, engine="not-a-real-engine")
    assert all(name in str(exc.value) for name in ENGINE_EFFICIENCY)


def test_kv_bytes_none_zeroes_kv_term_with_note():
    est = estimate_throughput(params_active=None, params_total=70_000_000_000,
                              bits_per_weight=8.0, kv_bytes_per_token=None,
                              workload=Workload(concurrent_requests=10, avg_context_tokens=4096),
                              device=resolve_device("h200-141gb"), n_gpus=8, engine="vllm")
    assert est is not None
    assert any("KV read not modeled" in n for n in est.assumptions.lines)


def test_prefill_falls_back_to_fp16_when_dtype_tflops_missing():
    # gh200-96gb-class custom device: has fp16 but no fp8 published.
    device = resolve_device("h200-141gb").model_copy(update={"tflops_fp8": None})
    est = estimate_throughput(params_active=None, params_total=70_000_000_000,
                              bits_per_weight=8.0, kv_bytes_per_token=62464.0,
                              workload=Workload(concurrent_requests=10, avg_context_tokens=4096),
                              device=device, n_gpus=8, engine="vllm")
    assert est is not None
    assert est.prefill_tps is not None
    assert any("fp16 TFLOPS" in n and "fp8" in n for n in est.assumptions.lines)


def test_prefill_none_when_no_tflops_published_at_all():
    device = resolve_device("h200-141gb").model_copy(
        update={"tflops_fp8": None, "tflops_fp16": None, "tflops_fp4": None}
    )
    est = estimate_throughput(params_active=None, params_total=70_000_000_000,
                              bits_per_weight=8.0, kv_bytes_per_token=62464.0,
                              workload=Workload(concurrent_requests=10, avg_context_tokens=4096),
                              device=device, n_gpus=8, engine="vllm")
    assert est is not None
    assert est.prefill_tps is None
    assert est.ttft_seconds is None
    assert any("prefill" in n.lower() for n in est.assumptions.lines)


def test_engine_constants_documented_per_engine():
    for engine, constants in ENGINE_EFFICIENCY.items():
        est = estimate_throughput(params_active=None, params_total=70_000_000_000,
                                  bits_per_weight=8.0, kv_bytes_per_token=62464.0,
                                  workload=Workload(concurrent_requests=10, avg_context_tokens=4096),
                                  device=resolve_device("h200-141gb"), n_gpus=8, engine=engine)
        assert est is not None
        assert any(engine in n for n in est.assumptions.lines)
        mbu_str = f"{constants['decode_mbu']:.2f}"
        assert any(mbu_str in n for n in est.assumptions.lines)
