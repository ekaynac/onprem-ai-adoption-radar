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


def test_models_discover_writes_proposals(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from radar.cli import app
    from radar.discovery.model_proposals import ModelProposal, load_model_proposals

    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])

    async def fake_discover(seeds, client, min_downloads=10000, limit=50, headers=None):
        return [ModelProposal(model_id="Qwen3-32B", name="Qwen3-32B", family="Qwen",
                              hf_repo="Qwen/Qwen3-32B", downloads=900000, likes=1200,
                              modality="text", reason="trending", suggested_id="hf-qwen3-32b")]
    monkeypatch.setattr("radar.discovery.hf_trending_models.discover_trending_models", fake_discover)

    result = runner.invoke(app, ["models", "discover", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    proposals = load_model_proposals(tmp_path / "data" / "proposed-model-seeds.yaml")
    assert any(p.hf_repo == "Qwen/Qwen3-32B" for p in proposals)
    assert "Qwen3-32B" in result.stdout


def test_models_devices_lists_presets(tmp_path):
    from typer.testing import CliRunner

    from radar.cli import app

    r = CliRunner().invoke(app, ["models", "devices"])
    assert r.exit_code == 0 and "rtx-4090-24gb" in r.stdout


def test_models_fit_reports_verdicts(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from radar.cli import app
    from radar.models import Ring
    from radar.models_radar.entities import (
        HardwareTier,
        Modality,
        ModelEntry,
        Openness,
        Platform,
        QuantVariant,
    )
    from radar.storage.run_store import RunStore
    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])
    rs = RunStore(tmp_path / "data" / "runs")
    rid = rs.create_run()
    e = ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3", params_total=8_000_000_000,
                   openness=Openness.OPEN_PERMISSIVE, hardware_tier=HardwareTier.LAPTOP,
                   ring=Ring.ADOPT, modality=Modality.TEXT,
                   quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5, est_memory_gb_4k=8.4,
                                        platform=Platform.GENERIC, source="hf:x")])
    rs.save_stage(rid, "model_cards", [e.model_dump(mode="json")])
    rs.update_meta(rid, {"kind": "models", "model_count": 1})

    r = runner.invoke(app, ["models", "fit", "--device", "rtx-4090-24gb", "--root", str(tmp_path)])
    assert r.exit_code == 0, r.stdout
    assert "qwen3-8b" in r.stdout and "fits" in r.stdout


def test_models_scan_persists_rings_and_list_shows_them(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from radar.cli import app
    from radar.models_radar.entities import (
        HardwareTier,
        ModelEntry,
        Openness,
        QuantVariant,
    )

    runner = CliRunner()
    runner.invoke(app, ["init", "--root", str(tmp_path)])

    async def fake_scan(seed_path, client):
        return [ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3",
                           params_total=8_000_000_000, openness=Openness.OPEN_PERMISSIVE,
                           hardware_tier=HardwareTier.LAPTOP, hf_downloads=1_000_000,
                           quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5,
                                                est_memory_gb_4k=8.0, source="hf:x")])]
    monkeypatch.setattr("radar.models_radar.scan.run_model_scan", fake_scan)

    assert runner.invoke(app, ["models", "scan", "--root", str(tmp_path)]).exit_code == 0
    out = runner.invoke(app, ["models", "list", "--root", str(tmp_path)])
    assert out.exit_code == 0, out.stdout
    assert "qwen3-8b" in out.stdout
    assert any(r in out.stdout for r in ("adopt", "pilot", "watch"))
    # history log written
    assert (tmp_path / "data" / "model-history.jsonl").exists()
