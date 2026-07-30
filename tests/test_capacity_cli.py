"""CLI surface for the capacity solver: `radar capacity plan` / `radar capacity max`
(spec §6, sub-project D, task 6).

All cases run against an empty tmp root (no `data/runs` scan) so the seed
fallback (`build_model_entry(seed, None, []) over load_model_seed`) is
exercised on every invocation — capacity planning must work on a fresh
clone, per the task brief.
"""

from __future__ import annotations

from typer.testing import CliRunner

from radar.cli import app


def test_capacity_plan_happy_path_uses_seed_fallback(tmp_path):
    runner = CliRunner()

    result = runner.invoke(app, [
        "capacity", "plan",
        "--model", "hf-deepseek-v4-pro",
        "--device", "hgx-h200-8",
        "--users", "50",
        "--context", "32768",
        "--quant", "FP8",
        "--kv-dtype", "fp8",
        "--root", str(tmp_path),
    ])

    assert result.exit_code == 0, result.stdout
    assert "16" in result.stdout  # n_gpus
    assert "2" in result.stdout  # n_nodes
    assert "Assumptions:" in result.stdout
    assert "no scan found — using bundled seed specs" in result.stdout
    # launch recipe (task 8): default engine is vllm
    assert "Launch recipe (vllm):" in result.stdout
    assert "--tensor-parallel-size 8" in result.stdout
    assert "--pipeline-parallel-size 2" in result.stdout
    assert "--kv-cache-dtype fp8" in result.stdout
    assert "--max-num-seqs 50" in result.stdout
    assert "--max-model-len 32768" in result.stdout
    assert "huggingface.co/deepseek-ai/DeepSeek-V4-Pro" in result.stdout
    # kW-first TCO block (task 9): 16 x H200 (700W) = 11.2 kW, electricity-only
    # $/Mtok since no datacenter device publishes indicative_price_usd today
    assert "TCO" in result.stdout
    assert "kW" in result.stdout
    assert "11.2" in result.stdout
    assert "/Mtok" in result.stdout
    assert "electricity only — no public list price" in result.stdout


def test_capacity_plan_tco_options_override_electricity_rate_and_amortization(tmp_path):
    runner = CliRunner()

    default_result = runner.invoke(app, [
        "capacity", "plan",
        "--model", "hf-deepseek-v4-pro",
        "--device", "hgx-h200-8",
        "--users", "50",
        "--context", "32768",
        "--quant", "FP8",
        "--kv-dtype", "fp8",
        "--root", str(tmp_path),
    ])
    doubled_rate_result = runner.invoke(app, [
        "capacity", "plan",
        "--model", "hf-deepseek-v4-pro",
        "--device", "hgx-h200-8",
        "--users", "50",
        "--context", "32768",
        "--quant", "FP8",
        "--kv-dtype", "fp8",
        "--electricity-usd-kwh", "0.24",
        "--amortization-months", "12",
        "--root", str(tmp_path),
    ])

    assert default_result.exit_code == 0, default_result.stdout
    assert doubled_rate_result.exit_code == 0, doubled_rate_result.stdout
    assert "$0.0245/Mtok" in default_result.stdout
    assert "$0.0490/Mtok" in doubled_rate_result.stdout  # rate doubled -> $/Mtok doubled
    assert "electricity rate $0.24/kWh" in doubled_rate_result.stdout
    assert "hardware amortized over 12 months" in doubled_rate_result.stdout


def test_capacity_plan_sglang_engine_renders_sglang_recipe(tmp_path):
    runner = CliRunner()

    result = runner.invoke(app, [
        "capacity", "plan",
        "--model", "hf-deepseek-v4-pro",
        "--device", "hgx-h200-8",
        "--users", "50",
        "--context", "32768",
        "--quant", "FP8",
        "--kv-dtype", "fp8",
        "--engine", "sglang",
        "--root", str(tmp_path),
    ])

    assert result.exit_code == 0, result.stdout
    assert "Launch recipe (sglang):" in result.stdout
    assert "--tp 8" in result.stdout
    assert "--pp 2" in result.stdout


def test_capacity_plan_llama_cpp_engine_skips_recipe_with_dim_note(tmp_path):
    runner = CliRunner()

    result = runner.invoke(app, [
        "capacity", "plan",
        "--model", "deepseek-v3",
        "--device", "hgx-h200-8",
        "--users", "10",
        "--context", "4096",
        "--quant", "FP8",
        "--engine", "llama-cpp",
        "--root", str(tmp_path),
    ])

    assert result.exit_code == 0, result.stdout
    assert "no launch recipe for llama-cpp — single-node tool" in result.stdout
    assert "Launch recipe" not in result.stdout


def test_capacity_max_infeasible_single_h200_reports_memory_reason(tmp_path):
    runner = CliRunner()

    result = runner.invoke(app, [
        "capacity", "max",
        "--model", "hf-deepseek-v4-pro",
        "--device", "h200-141gb",
        "--gpus", "1",
        "--context", "4096",
        "--quant", "FP8",
        "--root", str(tmp_path),
    ])

    assert result.exit_code == 2, result.stdout
    assert "Infeasible" in result.stdout
    assert "memory" in result.stdout.lower()


def test_capacity_plan_unknown_model_lists_available_ids(tmp_path):
    runner = CliRunner()

    result = runner.invoke(app, [
        "capacity", "plan",
        "--model", "does-not-exist",
        "--device", "hgx-h200-8",
        "--users", "10",
        "--context", "4096",
        "--root", str(tmp_path),
    ])

    assert result.exit_code == 1, result.stdout
    assert "does-not-exist" in result.stdout
    assert "deepseek-v3" in result.stdout  # a known seed id, proving the list rendered


def test_capacity_max_happy_path_prints_max_concurrency(tmp_path):
    runner = CliRunner()

    result = runner.invoke(app, [
        "capacity", "max",
        "--model", "deepseek-v3",
        "--device", "hgx-h200-8",
        "--gpus", "8",
        "--context", "32768",
        "--quant", "FP8",
        "--kv-dtype", "fp8",
        "--root", str(tmp_path),
    ])

    assert result.exit_code == 0, result.stdout
    assert "max concurrent" in result.stdout.lower()
    assert "Assumptions:" in result.stdout


def test_capacity_plan_bad_kv_dtype_is_a_readable_error_not_a_traceback(tmp_path):
    # radar.capacity.kv.kv_bytes_per_token raises a plain ValueError for an
    # unrecognized kv_dtype; the CLI must render it, not crash with a
    # traceback (global constraint: readable errors for bad kv_dtype/engine).
    runner = CliRunner()

    result = runner.invoke(app, [
        "capacity", "plan",
        "--model", "hf-deepseek-v4-pro",
        "--device", "hgx-h200-8",
        "--users", "50",
        "--context", "32768",
        "--quant", "FP8",
        "--kv-dtype", "bogus",
        "--root", str(tmp_path),
    ])

    assert result.exit_code == 1, result.stdout
    assert "Traceback" not in result.stdout
    assert "kv_dtype" in result.stdout
    assert "fp16" in result.stdout  # names a valid dtype


def test_capacity_max_zero_or_negative_gpus_is_a_clean_usage_error(tmp_path):
    # --gpus 0 used to crash with a raw ZeroDivisionError traceback (division
    # by world_size inside the memory/throughput math); --gpus -4 used to
    # silently "fit" (negative memory). Both must now fail fast as a typer
    # usage error (min=1 on the option) before the command body ever runs.
    runner = CliRunner()

    zero_result = runner.invoke(app, [
        "capacity", "max",
        "--model", "deepseek-v3",
        "--device", "hgx-h200-8",
        "--gpus", "0",
        "--context", "32768",
        "--quant", "FP8",
        "--root", str(tmp_path),
    ])
    negative_result = runner.invoke(app, [
        "capacity", "max",
        "--model", "deepseek-v3",
        "--device", "hgx-h200-8",
        "--gpus", "-4",
        "--context", "32768",
        "--quant", "FP8",
        "--root", str(tmp_path),
    ])

    for result in (zero_result, negative_result):
        # click's own parameter-validation error (IntRange) writes to
        # stderr, not stdout — check the combined `.output` stream.
        # Assert on "Usage:" rather than the flag name: rich truncates the
        # error panel under narrow CI terminals, cutting "--gpus" to "...",
        # and "Usage:" also distinguishes a usage error from the solver's
        # InfeasibleError path (which shares exit code 2 but never prints it).
        assert result.exit_code == 2, result.output
        assert "Traceback" not in result.output
        assert "Usage:" in result.output


def test_capacity_max_gpus_12_reports_idle_gpus_no_phantom_bandwidth(tmp_path):
    # _layout_for_count(12) collapses to TP8/PP1 (world_size=8) — 4 of the 12
    # requested GPUs are never addressed by this layout. The result must
    # disclose the idle GPUs rather than silently advertising 12-GPU
    # bandwidth for an 8-GPU-wide layout.
    runner = CliRunner()

    result = runner.invoke(app, [
        "capacity", "max",
        "--model", "deepseek-v3",
        "--device", "hgx-h200-8",
        "--gpus", "12",
        "--context", "32768",
        "--quant", "FP8",
        "--kv-dtype", "fp8",
        "--root", str(tmp_path),
    ])

    assert result.exit_code == 0, result.stdout
    assert "layout uses 8 of 12 GPUs" in result.stdout
    assert "4 GPU(s) idle" in result.stdout


def test_capacity_plan_zero_users_or_context_is_a_clean_usage_error(tmp_path):
    # Workload(...) construction used to sit outside the try block, so
    # --users 0 / --context 0 escaped as a raw pydantic ValidationError
    # traceback. min=1 on both options now rejects them before the command
    # body (and Workload construction) ever runs.
    runner = CliRunner()

    zero_users = runner.invoke(app, [
        "capacity", "plan",
        "--model", "deepseek-v3",
        "--device", "hgx-h200-8",
        "--users", "0",
        "--context", "32768",
        "--quant", "FP8",
        "--root", str(tmp_path),
    ])
    zero_context = runner.invoke(app, [
        "capacity", "plan",
        "--model", "deepseek-v3",
        "--device", "hgx-h200-8",
        "--users", "10",
        "--context", "0",
        "--quant", "FP8",
        "--root", str(tmp_path),
    ])

    for result in (zero_users, zero_context):
        # click's own parameter-validation error (IntRange) writes to
        # stderr, not stdout — check the combined `.output` stream.
        assert result.exit_code == 2, result.output
        assert "Traceback" not in result.output


def test_capacity_max_bad_engine_is_a_readable_error_not_a_traceback(tmp_path):
    # radar.capacity.throughput.estimate_throughput raises a plain ValueError
    # for an unrecognized engine; same readable-error requirement as above.
    runner = CliRunner()

    result = runner.invoke(app, [
        "capacity", "max",
        "--model", "deepseek-v3",
        "--device", "hgx-h200-8",
        "--gpus", "8",
        "--context", "32768",
        "--quant", "FP8",
        "--kv-dtype", "fp8",
        "--engine", "bogus-engine",
        "--root", str(tmp_path),
    ])

    assert result.exit_code == 1, result.stdout
    assert "Traceback" not in result.stdout
    assert "engine" in result.stdout.lower()
    assert "vllm" in result.stdout.lower()  # names a known engine
