# tests/test_models_radar_cli.py
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from radar.cli import app


def test_models_list_reads_latest_scan(tmp_path: Path, monkeypatch):
    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])

    # Stub the scan so the CLI test stays offline.
    from radar.models_radar.entities import HardwareTier, ModelEntry, QuantVariant

    async def fake_scan(seed_path, client):
        return [ModelEntry(id="llama-3.1-8b", name="Llama 3.1 8B", family="Llama",
                           hardware_tier=HardwareTier.LAPTOP,
                           quants=[QuantVariant(format="GGUF Q4_K_M", bits_per_weight=4.5,
                                                est_memory_gb_4k=5.4)])]
    monkeypatch.setattr("radar.models_radar.scan.run_model_scan", fake_scan)

    scan_result = runner.invoke(app, ["models", "scan", "--root", str(tmp_path)])
    assert scan_result.exit_code == 0, scan_result.stdout

    list_result = runner.invoke(app, ["models", "list", "--root", str(tmp_path)])
    assert list_result.exit_code == 0, list_result.stdout
    assert "llama-3.1-8b" in list_result.stdout
    assert "laptop" in list_result.stdout
