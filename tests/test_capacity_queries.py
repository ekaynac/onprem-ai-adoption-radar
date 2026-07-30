"""Service-level tests for the MCP capacity-solver adapter (spec §6, task 7).

All cases run against an empty tmp root (no `data/runs` scan) so the seed
fallback (`_entries_or_seed` -> `load_model_seed` + `build_model_entry(seed,
None, [])`) is exercised on every invocation — same convention as
`tests/test_capacity_cli.py`. The service must never raise across the MCP
boundary: InfeasibleError/DeviceError/plain ValueError all fold into a
structured `{"feasible": False, "reasons": [...]}` dict; only an unknown
`model_id` returns `None`.
"""

from __future__ import annotations

import pytest

from radar.mcp_server.capacity_queries import CapacityQueryService


def test_plan_capacity_happy_path_feasible(tmp_path):
    service = CapacityQueryService(tmp_path)

    result = service.plan_capacity(
        "hf-deepseek-v4-pro", "hgx-h200-8",
        concurrent_requests=50, avg_context_tokens=32768,
        quant="FP8", kv_dtype="fp8",
    )

    assert result is not None
    assert result["feasible"] is True
    assert result["n_gpus"] == 16
    assert result["n_nodes"] == 2
    assert result["assumptions"]["lines"]  # non-empty assumption sheet
    # launch recipe (task 8): default engine is vllm
    assert "recipe" in result
    assert "--tensor-parallel-size 8" in result["recipe"]
    assert "--pipeline-parallel-size 2" in result["recipe"]
    assert "huggingface.co/deepseek-ai/DeepSeek-V4-Pro" in result["recipe"]
    # kW-first TCO (task 9): 16 x H200 (700W) = 11.2 kW; electricity-only
    # $/Mtok since hgx-h200-8 publishes no indicative_price_usd
    assert result["tco"] is not None
    assert result["tco"]["fleet_power_kw"] == pytest.approx(11.2)
    assert result["tco"]["usd_per_million_tokens"] is not None
    assert any("no public list price" in line for line in result["tco"]["assumptions"]["lines"])


def test_plan_capacity_llama_cpp_engine_has_no_recipe_key(tmp_path):
    service = CapacityQueryService(tmp_path)

    result = service.plan_capacity(
        "deepseek-v3", "hgx-h200-8",
        concurrent_requests=10, avg_context_tokens=4096,
        quant="FP8", engine="llama-cpp",
    )

    assert result is not None
    assert result["feasible"] is True
    assert "recipe" not in result
    assert "tco" in result  # present regardless of engine, unlike "recipe"


def test_plan_capacity_device_without_published_tdp_has_none_tco(tmp_path):
    # ascend-910b-64gb publishes no tdp_watts — the "tco" key stays present
    # (never omitted) but its value is None rather than raising or guessing.
    service = CapacityQueryService(tmp_path)

    result = service.plan_capacity(
        "smollm2-1.7b", "ascend-910b-64gb",
        concurrent_requests=10, avg_context_tokens=4096,
    )

    assert result is not None
    assert result["feasible"] is True
    assert result["tco"] is None


def test_max_workload_infeasible_single_h200_returns_reasons_dict(tmp_path):
    service = CapacityQueryService(tmp_path)

    result = service.max_workload(
        "hf-deepseek-v4-pro", "h200-141gb", n_gpus=1,
        avg_context_tokens=4096, quant="FP8",
    )

    assert result is not None
    assert result["feasible"] is False
    assert result["model_id"] == "hf-deepseek-v4-pro"
    assert result["device"] == "h200-141gb"
    assert result["reasons"]
    assert any("memory" in r.lower() for r in result["reasons"])


def test_plan_capacity_bad_device_returns_feasible_false_not_an_exception(tmp_path):
    service = CapacityQueryService(tmp_path)

    result = service.plan_capacity(
        "hf-deepseek-v4-pro", "not-a-real-device",
        concurrent_requests=10, avg_context_tokens=4096,
    )

    assert result is not None
    assert result["feasible"] is False
    assert result["device"] == "not-a-real-device"
    assert any("not-a-real-device" in r for r in result["reasons"])


def test_plan_capacity_unknown_model_returns_none(tmp_path):
    service = CapacityQueryService(tmp_path)

    assert service.plan_capacity(
        "does-not-exist", "hgx-h200-8",
        concurrent_requests=10, avg_context_tokens=4096,
    ) is None


def test_max_workload_unknown_model_returns_none(tmp_path):
    service = CapacityQueryService(tmp_path)

    assert service.max_workload(
        "does-not-exist", "hgx-h200-8", n_gpus=8, avg_context_tokens=4096,
    ) is None


def test_compare_devices_unknown_model_returns_none(tmp_path):
    service = CapacityQueryService(tmp_path)

    assert service.compare_devices(
        "does-not-exist", ["hgx-h200-8"],
        concurrent_requests=10, avg_context_tokens=4096,
    ) is None


def test_compare_devices_returns_one_row_per_device_in_order(tmp_path):
    service = CapacityQueryService(tmp_path)
    devices = ["hgx-h200-8", "hgx-b200-8", "mi300x-oam-8"]

    rows = service.compare_devices(
        "hf-deepseek-v4-pro", devices,
        concurrent_requests=50, avg_context_tokens=32768,
        quant="FP8", kv_dtype="fp8",
    )

    assert rows is not None
    assert len(rows) == 3
    assert [row["device"] for row in rows] == devices
    for row in rows:
        assert "feasible" in row
        if row["feasible"]:
            assert "n_gpus" in row
        else:
            assert row["reasons"]


def test_compare_devices_bogus_device_id_gets_its_own_row_not_a_crash(tmp_path):
    service = CapacityQueryService(tmp_path)
    devices = ["hgx-h200-8", "hgx-b200-8", "mi300x-oam-8", "bogus-device-id"]

    rows = service.compare_devices(
        "hf-deepseek-v4-pro", devices,
        concurrent_requests=50, avg_context_tokens=32768,
        quant="FP8", kv_dtype="fp8",
    )

    assert rows is not None
    assert len(rows) == 4
    assert [row["device"] for row in rows] == devices
    bogus_row = rows[-1]
    assert bogus_row["feasible"] is False
    assert any("bogus-device-id" in r for r in bogus_row["reasons"])
