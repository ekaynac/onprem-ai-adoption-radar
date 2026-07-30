"""kW-first TCO estimates from a solved CapacityPlan (spec §6.5, sub-project D task 9).

The V4-Pro / hgx-h200-8 / 50-users / 32k-ctx / FP8 / kv-fp8 scenario is the
same anchor ``tests/test_capacity_solver.py`` pins for ``plan_capacity``
(n_gpus=16, tp=8, pp=2) — reused here so the kW math is checked against a
real, already-verified solved plan. Its ``aggregate_decode_tps`` is read off
the plan object rather than hardcoded (Task 6's review recorded ~15224, but
the solver is the source of truth, not a comment).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from radar.capacity.solver import plan_capacity
from radar.capacity.tco import (
    DEFAULT_AMORTIZATION_MONTHS,
    DEFAULT_ELECTRICITY_USD_PER_KWH,
    estimate_tco,
)
from radar.capacity.types import Workload
from radar.models_radar.assemble import build_model_entry
from radar.models_radar.devices import resolve_device
from radar.models_radar.entities import ModelEntry
from radar.models_radar.seed import load_model_seed


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _entry(seed_id: str) -> ModelEntry:
    seeds = {s.id: s for s in load_model_seed(_REPO_ROOT / "config" / "model-seed.yaml")}
    return build_model_entry(seeds[seed_id], None, [])


def _v4_pro_plan():
    # Same anchor as test_capacity_solver.py / test_capacity_recipe.py
    return plan_capacity(
        _entry("hf-deepseek-v4-pro"), "hgx-h200-8",
        Workload(concurrent_requests=50, avg_context_tokens=32768),
        quant_format="FP8", kv_dtype="fp8",
    )


def test_defaults_are_the_documented_values():
    assert DEFAULT_ELECTRICITY_USD_PER_KWH == 0.12
    assert DEFAULT_AMORTIZATION_MONTHS == 36


def test_v4_pro_hgx_h200_kw_math_hand_verified():
    plan = _v4_pro_plan()
    device = resolve_device(plan.device_id)
    assert device.tdp_watts == 700  # H200 board TDP
    assert device.indicative_price_usd is None  # confirmed against device-seed.yaml

    result = estimate_tco(plan)

    assert result is not None
    # 16 GPUs x 700W / 1000 = 11.2 kW
    assert result.fleet_power_kw == pytest.approx(11.2)

    aggregate_tps = plan.throughput.aggregate_decode_tps
    expected_tps_per_kw = round(aggregate_tps / 11.2, 1)
    assert result.tokens_per_sec_per_kw == pytest.approx(expected_tps_per_kw)

    expected_usd_per_mtok = round(
        (11.2 * DEFAULT_ELECTRICITY_USD_PER_KWH / 3600) / (aggregate_tps / 1e6), 4
    )
    assert result.usd_per_million_tokens == pytest.approx(expected_usd_per_mtok)


def test_v4_pro_assumptions_disclose_capex_exclusion_and_tdp_caveat():
    plan = _v4_pro_plan()

    result = estimate_tco(plan)

    assert result is not None
    lines = " ".join(result.assumptions.lines)
    assert "no public list price" in lines
    assert "NVIDIA HGX H200 8-GPU" in lines  # names the device, per spec
    assert "board TDP" in lines
    assert "host CPUs" in lines and "cooling" in lines
    assert "electricity rate $0.12/kWh" in lines
    assert "36 months" in lines


def test_device_without_published_tdp_returns_none():
    # ascend-910b-64gb publishes memory_bandwidth_gbs + tflops_fp16 (so
    # throughput is NOT None) but no tdp_watts — isolates the TDP-missing
    # reason from the throughput-missing reason.
    entry = _entry("smollm2-1.7b")
    plan = plan_capacity(
        entry, "ascend-910b-64gb",
        Workload(concurrent_requests=10, avg_context_tokens=4096),
    )
    device = resolve_device(plan.device_id)
    assert device.tdp_watts is None
    assert plan.throughput is not None  # sanity: isolates the TDP reason

    assert estimate_tco(plan) is None


def test_non_default_electricity_rate_scales_dollar_per_mtok_proportionally():
    plan = _v4_pro_plan()

    baseline = estimate_tco(plan)
    doubled_rate = estimate_tco(plan, electricity_usd_per_kwh=DEFAULT_ELECTRICITY_USD_PER_KWH * 2)

    assert baseline is not None and doubled_rate is not None
    # No hardware term for this device (no indicative_price_usd) — pure
    # electricity cost, so doubling the rate exactly doubles $/Mtok.
    assert doubled_rate.usd_per_million_tokens == pytest.approx(
        baseline.usd_per_million_tokens * 2, rel=1e-6
    )
    assert doubled_rate.fleet_power_kw == baseline.fleet_power_kw
    assert doubled_rate.tokens_per_sec_per_kw == baseline.tokens_per_sec_per_kw


def test_non_default_amortization_months_changes_dollar_per_mtok_when_price_known():
    # rtx-4090-24gb is one of the few devices with a published
    # indicative_price_usd, so this isolates the amortization-months effect
    # on the hardware term (zero-price devices are unaffected by this knob).
    entry = _entry("smollm2-1.7b")
    plan = plan_capacity(
        entry, "rtx-4090-24gb",
        Workload(concurrent_requests=10, avg_context_tokens=4096),
    )
    device = resolve_device(plan.device_id)
    assert device.indicative_price_usd is not None

    result_36mo = estimate_tco(plan)  # default
    result_12mo = estimate_tco(plan, amortization_months=12)

    assert result_36mo is not None and result_12mo is not None
    assert "no public list price" not in " ".join(result_36mo.assumptions.lines)
    # Faster amortization -> higher hardware cost per token -> higher $/Mtok.
    assert result_12mo.usd_per_million_tokens > result_36mo.usd_per_million_tokens
