"""launch_recipe: copy-pasteable launch configs from a solved CapacityPlan
(spec §6.4, sub-project D task 8).

The V4-Pro / hgx-h200-8 / 50-users / 32k-ctx / FP8 / kv-fp8 scenario is the
same anchor ``tests/test_capacity_solver.py`` pins for ``plan_capacity``
(n_gpus=16, tp=8, pp=2) — reused here so the recipe's flags are checked
against a real, already-verified solved plan rather than a hand-built stub.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from radar.capacity.recipe import launch_recipe
from radar.capacity.solver import plan_capacity
from radar.capacity.types import Workload
from radar.models_radar.assemble import build_model_entry
from radar.models_radar.entities import ModelEntry
from radar.models_radar.seed import load_model_seed


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _entry(seed_id: str) -> ModelEntry:
    seeds = {s.id: s for s in load_model_seed(_REPO_ROOT / "config" / "model-seed.yaml")}
    return build_model_entry(seeds[seed_id], None, [])


def _v4_pro_plan():
    # Same anchor as test_capacity_solver.py::test_anchor_v4_pro_needs_two_h200_nodes_for_50_users
    return plan_capacity(
        _entry("hf-deepseek-v4-pro"), "hgx-h200-8",
        Workload(concurrent_requests=50, avg_context_tokens=32768),
        quant_format="FP8", kv_dtype="fp8",
    )


def test_vllm_recipe_has_expected_flags_for_v4_pro():
    plan = _v4_pro_plan()
    entry = _entry("hf-deepseek-v4-pro")

    recipe = launch_recipe(plan, entry, engine="vllm", kv_dtype="fp8")

    assert "vllm serve deepseek-ai/DeepSeek-V4-Pro" in recipe
    assert "--tensor-parallel-size 8" in recipe
    assert "--pipeline-parallel-size 2" in recipe
    assert "--kv-cache-dtype fp8" in recipe
    assert "--max-num-seqs 50" in recipe
    assert "--max-model-len 32768" in recipe
    assert "--quantization fp8" in recipe  # FP8-resolved quant format
    assert "--gpu-memory-utilization 0.85" in recipe
    assert "huggingface.co/deepseek-ai/DeepSeek-V4-Pro" in recipe


def test_sglang_recipe_uses_tp_flag_and_pp_when_greater_than_one():
    plan = _v4_pro_plan()
    entry = _entry("hf-deepseek-v4-pro")

    recipe = launch_recipe(plan, entry, engine="sglang", kv_dtype="fp8")

    assert "sglang.launch_server --model-path deepseek-ai/DeepSeek-V4-Pro --tp 8" in recipe
    assert "--pp 2" in recipe
    assert "--kv-cache-dtype fp8_e4m3" in recipe
    assert "--max-running-requests 50" in recipe
    assert "--context-length 32768" in recipe


def test_tensorrt_llm_recipe_is_a_caution_recipe_with_build_note():
    plan = _v4_pro_plan()
    entry = _entry("hf-deepseek-v4-pro")

    recipe = launch_recipe(plan, entry, engine="tensorrt-llm")

    assert "trtllm-serve deepseek-ai/DeepSeek-V4-Pro" in recipe
    assert "--tp_size 8" in recipe
    assert "--pp_size 2" in recipe
    assert "NOTE" in recipe
    assert "engine-build step" in recipe
    assert "github.com/NVIDIA/TensorRT-LLM" in recipe


def test_pipeline_parallel_flag_omitted_when_pp_is_one():
    # Same anchor as test_capacity_solver.py::test_anchor_deepseek_v3_fits_one_h200_node_fp8
    entry = _entry("deepseek-v3")
    plan = plan_capacity(
        entry, "hgx-h200-8",
        Workload(concurrent_requests=20, avg_context_tokens=32768),
        quant_format="FP8", kv_dtype="fp8",
    )
    assert plan.n_gpus == 8 and plan.parallelism.pipeline_parallel == 1  # sanity

    recipe = launch_recipe(plan, entry, engine="vllm", kv_dtype="fp8")
    assert "--pipeline-parallel-size" not in recipe

    sg_recipe = launch_recipe(plan, entry, engine="sglang", kv_dtype="fp8")
    assert "--pp " not in sg_recipe and not sg_recipe.rstrip().endswith("--pp")


def test_unknown_engine_raises_value_error_listing_supported_engines():
    plan = _v4_pro_plan()
    entry = _entry("hf-deepseek-v4-pro")

    with pytest.raises(ValueError) as exc:
        launch_recipe(plan, entry, engine="bogus-engine")

    message = str(exc.value)
    assert "vllm" in message
    assert "sglang" in message
    assert "tensorrt-llm" in message


def test_llama_cpp_is_out_of_recipe_scope():
    # llama-cpp is a valid engine for plan_capacity/estimate_throughput but is
    # deliberately excluded from launch_recipe's scope (single-node tool) —
    # callers (CLI/MCP) special-case it rather than calling launch_recipe.
    plan = _v4_pro_plan()
    entry = _entry("hf-deepseek-v4-pro")

    with pytest.raises(ValueError) as exc:
        launch_recipe(plan, entry, engine="llama-cpp")

    assert "llama-cpp" in str(exc.value)


def test_hf_repo_none_uses_placeholder_and_note():
    plan = _v4_pro_plan()
    entry = _entry("hf-deepseek-v4-pro").model_copy(update={"hf_repo": None})

    recipe = launch_recipe(plan, entry, engine="vllm", kv_dtype="fp8")

    assert "<model-path>" in recipe
    assert "replace <model-path> with your local weights path" in recipe
    assert "huggingface.co" not in recipe


def test_kv_dtype_other_than_fp16_or_fp8_gets_a_check_support_note():
    plan = _v4_pro_plan()
    entry = _entry("hf-deepseek-v4-pro")

    recipe = launch_recipe(plan, entry, engine="vllm", kv_dtype="fp4")

    assert "--kv-cache-dtype" not in recipe
    assert "kv-dtype fp4: check engine support" in recipe


def test_fp16_kv_dtype_needs_no_flag_and_no_note():
    plan = _v4_pro_plan()
    entry = _entry("hf-deepseek-v4-pro")

    recipe = launch_recipe(plan, entry, engine="vllm", kv_dtype="fp16")

    assert "--kv-cache-dtype" not in recipe
    assert "check engine support" not in recipe


def test_recipe_is_a_plain_str():
    plan = _v4_pro_plan()
    entry = _entry("hf-deepseek-v4-pro")

    recipe = launch_recipe(plan, entry, engine="vllm", kv_dtype="fp8")

    assert isinstance(recipe, str)
