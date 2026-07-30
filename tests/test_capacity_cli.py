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
