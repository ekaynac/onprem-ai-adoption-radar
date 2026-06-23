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


# ---------------------------------------------------------------------------
# models promote tests
# ---------------------------------------------------------------------------

_SEED_YAML = """\
version: "1.0"
models:
  - id: llama-3.1-8b
    name: Llama 3.1 8B Instruct
    family: Llama
    hf_repo: meta-llama/Llama-3.1-8B-Instruct
    backer: {name: "Meta", type: big_tech}
    params_total: 8000000000

  - id: qwen3-8b
    name: Qwen3 8B
    family: Qwen3
    hf_repo: Qwen/Qwen3-8B
    backer: {name: "Alibaba", type: big_tech}
    params_total: 8000000000
"""


def _setup_promote_env(tmp_path: Path) -> None:
    """Write seed file and proposals used by promote tests."""
    from radar.discovery.model_proposals import ModelProposal, write_model_proposals

    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "model-seed.yaml").write_text(_SEED_YAML, encoding="utf-8")

    proposals = [
        ModelProposal(
            model_id="Phi-4-14B",
            name="Phi-4-14B",
            family="Phi",
            hf_repo="microsoft/Phi-4-14B",
            downloads=500000,
            likes=1000,
            modality="text",
            suggested_id="hf-phi-4-14b",
        ),
        # Junk: republisher org
        ModelProposal(
            model_id="Phi-4-GGUF",
            name="Phi-4-GGUF",
            family="Phi",
            hf_repo="bartowski/Phi-4-GGUF",
            downloads=500000,
            likes=500,
            modality="text",
            suggested_id="hf-phi-4-gguf",
        ),
        # Already seeded repo
        ModelProposal(
            model_id="Llama-3.1-8B-Instruct",
            name="Llama 3.1 8B Instruct",
            family="Llama",
            hf_repo="meta-llama/Llama-3.1-8B-Instruct",
            downloads=5000000,
            likes=9000,
            modality="text",
            suggested_id="hf-llama-3-1-8b",
        ),
    ]
    write_model_proposals(tmp_path / "data" / "proposed-model-seeds.yaml", proposals)


def test_models_promote_appends_clean_model(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from radar.cli import app
    from radar.models_radar.collectors.huggingface import HFModelData
    from radar.models_radar.seed import load_model_seed

    runner = CliRunner()
    _setup_promote_env(tmp_path)

    async def fake_fetch_hf_model(hf_repo: str, client):
        if hf_repo == "microsoft/Phi-4-14B":
            return HFModelData(
                params_total=14_000_000_000,
                context_length=128000,
                last_modified="2025-01-15T00:00:00Z",
            )
        return None

    monkeypatch.setattr(
        "radar.models_radar.collectors.huggingface.fetch_hf_model",
        fake_fetch_hf_model,
    )

    result = runner.invoke(
        app,
        ["models", "promote", "--min-downloads", "100000", "--root", str(tmp_path)],
    )
    assert result.exit_code == 0, result.stdout

    seed_text = (tmp_path / "config" / "model-seed.yaml").read_text(encoding="utf-8")
    assert "hf-phi-4-14b" in seed_text or "Phi-4-14B" in seed_text

    loaded = load_model_seed(tmp_path / "config" / "model-seed.yaml")
    ids = [s.id for s in loaded]
    assert len(ids) == len(set(ids)), "Duplicate IDs after promotion"

    assert "bartowski/Phi-4-GGUF" not in seed_text
    assert seed_text.count("meta-llama/Llama-3.1-8B-Instruct") == 1


def test_models_promote_dry_run_does_not_write(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from radar.cli import app
    from radar.models_radar.collectors.huggingface import HFModelData

    runner = CliRunner()
    _setup_promote_env(tmp_path)

    original_text = (tmp_path / "config" / "model-seed.yaml").read_text(encoding="utf-8")

    async def fake_fetch_hf_model(hf_repo: str, client):
        if hf_repo == "microsoft/Phi-4-14B":
            return HFModelData(
                params_total=14_000_000_000,
                context_length=128000,
                last_modified="2025-01-15T00:00:00Z",
            )
        return None

    monkeypatch.setattr(
        "radar.models_radar.collectors.huggingface.fetch_hf_model",
        fake_fetch_hf_model,
    )

    result = runner.invoke(
        app,
        ["models", "promote", "--dry-run", "--min-downloads", "100000", "--root", str(tmp_path)],
    )
    assert result.exit_code == 0, result.stdout

    after_text = (tmp_path / "config" / "model-seed.yaml").read_text(encoding="utf-8")
    assert after_text == original_text, "dry-run must not modify the seed file"

    assert "microsoft/Phi-4-14B" in result.stdout or "hf-phi-4-14b" in result.stdout


def test_models_promote_no_params_qualifies_nothing(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from radar.cli import app
    from radar.models_radar.collectors.huggingface import HFModelData

    runner = CliRunner()
    _setup_promote_env(tmp_path)

    original_text = (tmp_path / "config" / "model-seed.yaml").read_text(encoding="utf-8")

    async def fake_fetch_hf_model(hf_repo: str, client):
        return HFModelData()  # no params_total

    monkeypatch.setattr(
        "radar.models_radar.collectors.huggingface.fetch_hf_model",
        fake_fetch_hf_model,
    )

    result = runner.invoke(
        app,
        ["models", "promote", "--min-downloads", "100000", "--root", str(tmp_path)],
    )
    assert result.exit_code == 0, result.stdout

    after_text = (tmp_path / "config" / "model-seed.yaml").read_text(encoding="utf-8")
    assert after_text == original_text, "file must not change when no models qualify"

    assert "No new models qualified" in result.stdout
