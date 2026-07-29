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

    async def fake_scan(seed_path, client, retrieved_at=None):
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


def test_models_devices_lists_nodes_and_clusters(tmp_path):
    from typer.testing import CliRunner

    from radar.cli import app

    r = CliRunner().invoke(app, ["models", "devices"])
    assert r.exit_code == 0
    assert "Devices" in r.stdout and "Nodes" in r.stdout and "Clusters" in r.stdout
    assert "hgx-h200-8" in r.stdout
    assert "2x-hgx-h200-8" in r.stdout


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

    async def fake_scan(seed_path, client, retrieved_at=None):
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
    """Write seed file, proposals, and candidate observations used by promote tests."""
    from datetime import UTC, datetime, timedelta

    from radar.discovery.model_proposals import ModelProposal, write_model_proposals
    from radar.storage.model_candidate_log import (
        ModelCandidateObservation,
        append_model_candidates,
    )

    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "model-seed.yaml").write_text(_SEED_YAML, encoding="utf-8")

    # Sustained download momentum for the one proposal expected to survive the
    # promote gate: 3 distinct days, 5-day span, +66% growth (all above threshold).
    # Dated relative to "now" (rather than a fixed calendar date) so the rows stay
    # inside the CLI's 14-day momentum window regardless of when the suite runs.
    now = datetime.now(UTC)
    observations = [
        ModelCandidateObservation(hf_repo="microsoft/Phi-4-14B", name="Phi-4-14B",
                                  family="Phi", downloads=300000, likes=800,
                                  observed_at=now - timedelta(days=6)),
        ModelCandidateObservation(hf_repo="microsoft/Phi-4-14B", name="Phi-4-14B",
                                  family="Phi", downloads=400000, likes=900,
                                  observed_at=now - timedelta(days=3)),
        ModelCandidateObservation(hf_repo="microsoft/Phi-4-14B", name="Phi-4-14B",
                                  family="Phi", downloads=500000, likes=1000,
                                  observed_at=now - timedelta(days=1)),
    ]
    append_model_candidates(tmp_path / "data" / "model-candidate-observations.jsonl", observations)

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
    assert "hf-phi-4-14b" in seed_text

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


# ---------------------------------------------------------------------------
# models verify tests
# ---------------------------------------------------------------------------


def _write_model_seed(tmp_path: Path, models_yaml_body: str) -> None:
    """Write a minimal config/model-seed.yaml with the given `models:` list body."""
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "model-seed.yaml").write_text(
        f'version: "1.0"\nmodels:\n{models_yaml_body}', encoding="utf-8"
    )


def test_models_verify_reports_drift_and_check_exits_1(tmp_path: Path, monkeypatch):
    import radar.cli as cli_mod
    from radar.models_radar.collectors.huggingface import HFModelData
    from radar.models_radar.entities import ArchitectureSpec

    _write_model_seed(tmp_path, """\
  - id: drift-model
    name: Drift-7B
    family: Drift
    hf_repo: org/drift
    params_total: 7000000000
    spec_verified: true
    architecture:
      num_key_value_heads: 8
""")

    async def fake_fetch(repo, client):
        return HFModelData(
            params_total=7_600_000_000,   # drifts from the seed's 7.0B (ratio ~1.09x)
            architecture=ArchitectureSpec(num_key_value_heads=4),
        )

    monkeypatch.setattr(cli_mod, "_verify_fetch_hf_model", fake_fetch, raising=False)

    runner = CliRunner()
    result = runner.invoke(cli_mod.app, ["models", "verify", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.stdout           # report-only without --check
    assert "DRIFT drift-model.params_total" in result.stdout
    assert "DRIFT drift-model.architecture.num_key_value_heads" in result.stdout

    checked = runner.invoke(cli_mod.app, ["models", "verify", "--root", str(tmp_path), "--check"])
    assert checked.exit_code == 1                         # verified seed drifted


def test_models_verify_no_drift_reports_ok(tmp_path: Path, monkeypatch):
    import radar.cli as cli_mod
    from radar.models_radar.collectors.huggingface import HFModelData

    _write_model_seed(tmp_path, """\
  - id: stable-model
    name: Stable-7B
    family: Stable
    hf_repo: org/stable
    params_total: 7000000000
    spec_verified: true
""")

    async def fake_fetch(repo, client):
        return HFModelData(params_total=7_000_000_000)

    monkeypatch.setattr(cli_mod, "_verify_fetch_hf_model", fake_fetch, raising=False)

    runner = CliRunner()
    result = runner.invoke(cli_mod.app, ["models", "verify", "--root", str(tmp_path), "--check"])
    assert result.exit_code == 0, result.stdout
    assert "OK: 1 seed verified, no drift" in result.stdout


def test_models_verify_unreachable_repo_is_skip_not_failure(tmp_path: Path, monkeypatch):
    import radar.cli as cli_mod

    _write_model_seed(tmp_path, """\
  - id: unreachable-model
    name: Unreachable-7B
    family: Unreachable
    hf_repo: org/unreachable
    params_total: 7000000000
    spec_verified: true
""")

    async def fake_fetch(repo, client):
        return None

    monkeypatch.setattr(cli_mod, "_verify_fetch_hf_model", fake_fetch, raising=False)

    runner = CliRunner()
    result = runner.invoke(cli_mod.app, ["models", "verify", "--root", str(tmp_path), "--check"])
    assert result.exit_code == 0, result.stdout            # unreachable never fails the command
    assert "skip unreachable-model" in result.stdout
    # A fully-skipped run must never claim seeds were verified.
    assert "OK:" not in result.stdout
    assert "checked 0 of 1 seeds, no drift (1 unreachable)" in result.stdout


def test_models_verify_fetch_exception_is_skip_not_crash(tmp_path: Path, monkeypatch):
    """One seed's fetcher raising (e.g. a malformed API body) must not crash the
    whole command and lose every other seed's report — it's caught in the CLI
    layer and reported as a skip, same as an ordinary unreachable repo."""
    import radar.cli as cli_mod
    from radar.models_radar.collectors.huggingface import HFModelData

    _write_model_seed(tmp_path, """\
  - id: crash-model
    name: Crash-7B
    family: Crash
    hf_repo: org/crash
    params_total: 7000000000
    spec_verified: true

  - id: ok-model
    name: Ok-7B
    family: Ok
    hf_repo: org/ok
    params_total: 7000000000
    spec_verified: true
""")

    async def fake_fetch(repo, client):
        if repo == "org/crash":
            raise AttributeError("'NoneType' object has no attribute 'get'")
        return HFModelData(params_total=7_000_000_000)

    monkeypatch.setattr(cli_mod, "_verify_fetch_hf_model", fake_fetch, raising=False)

    runner = CliRunner()
    result = runner.invoke(cli_mod.app, ["models", "verify", "--root", str(tmp_path), "--check"])
    assert result.exit_code == 0, result.stdout        # a raising fetcher never fails the command
    assert "skip crash-model: AttributeError" in result.stdout
    # ok-model was still fetched and reported (no drift, and not lumped in as unreachable).
    assert "checked 1 of 2 seeds, no drift (1 unreachable)" in result.stdout


def test_models_verify_never_modifies_seed_file(tmp_path: Path, monkeypatch):
    import radar.cli as cli_mod
    from radar.models_radar.collectors.huggingface import HFModelData

    _write_model_seed(tmp_path, """\
  - id: drift-model
    name: Drift-7B
    family: Drift
    hf_repo: org/drift
    params_total: 7000000000
    spec_verified: true
""")
    original_text = (tmp_path / "config" / "model-seed.yaml").read_text(encoding="utf-8")

    async def fake_fetch(repo, client):
        return HFModelData(params_total=7_600_000_000)

    monkeypatch.setattr(cli_mod, "_verify_fetch_hf_model", fake_fetch, raising=False)

    runner = CliRunner()
    runner.invoke(cli_mod.app, ["models", "verify", "--root", str(tmp_path), "--check"])

    after_text = (tmp_path / "config" / "model-seed.yaml").read_text(encoding="utf-8")
    assert after_text == original_text, "verify must never modify the seed file"


def test_models_verify_packed_quant_params_total_is_note_not_drift(
    tmp_path: Path, monkeypatch
):
    """FP4/NVFP4-packed HF repos report a safetensors element count roughly
    1.5x-2x below the real published param total (see config/model-seed.yaml's
    hf-deepseek-v4-flash and hf-glm-5-2-nvfp4 comments, corrected 2026-07-28:
    observed ratios 1.53x-1.98x). Treating that as DRIFT on a spec_verified
    seed would make the weekly --check gate permanently red for a known,
    documented, deliberate seed/HF disagreement — so params_total comparisons
    with a ratio inside the packed-quant band ([1.4x, 2.5x], with margin above
    and below the observed range) are reported as a note, never DRIFT, and
    never trip --check.
    """
    import radar.cli as cli_mod
    from radar.models_radar.collectors.huggingface import HFModelData

    _write_model_seed(tmp_path, """\
  - id: packed-model
    name: Packed-284B
    family: Packed
    hf_repo: org/packed
    params_total: 284000000000
    spec_verified: true
""")

    async def fake_fetch(repo, client):
        return HFModelData(params_total=158_069_433_298)  # ~1.80x, matches hf-deepseek-v4-flash

    monkeypatch.setattr(cli_mod, "_verify_fetch_hf_model", fake_fetch, raising=False)

    runner = CliRunner()
    result = runner.invoke(cli_mod.app, ["models", "verify", "--root", str(tmp_path), "--check"])
    assert result.exit_code == 0, result.stdout
    assert "DRIFT" not in result.stdout
    assert "note packed-model: params_total differs by" in result.stdout
    assert "packed-quant artifact" in result.stdout


def test_models_verify_small_params_total_diff_is_note_not_drift(
    tmp_path: Path, monkeypatch
):
    """Published model cards quote a rounded headline total ("671B") while HF's
    safetensors element count is exact ("684.53B") — a ~2% gap that is not real
    drift (see deepseek-r1/deepseek-v3, corrected 2026-07-28). Differences
    within 3% are reported as a note and never trip --check."""
    import radar.cli as cli_mod
    from radar.models_radar.collectors.huggingface import HFModelData

    _write_model_seed(tmp_path, """\
  - id: rounded-model
    name: Rounded-671B
    family: Rounded
    hf_repo: org/rounded
    params_total: 671000000000
    spec_verified: true
""")

    async def fake_fetch(repo, client):
        return HFModelData(params_total=684_531_386_000)  # ~+2.0%, matches deepseek-r1/-v3

    monkeypatch.setattr(cli_mod, "_verify_fetch_hf_model", fake_fetch, raising=False)

    runner = CliRunner()
    result = runner.invoke(cli_mod.app, ["models", "verify", "--root", str(tmp_path), "--check"])
    assert result.exit_code == 0, result.stdout
    assert "DRIFT" not in result.stdout
    assert "note rounded-model: params_total differs by 2.0% (published-rounded total)" in (
        result.stdout
    )


def test_models_verify_context_length_mismatch_is_note_never_drift(
    tmp_path: Path, monkeypatch
):
    """config.json's max_position_embeddings is a different quantity than the
    seed's card-derived context_length (often YaRN/RoPE-scaling headroom, see
    deepseek-v3: card says 131072, config.json's max_position_embeddings is
    163840). A mismatch is always a note, never DRIFT, even on a spec_verified
    seed — so it can never trip --check."""
    import radar.cli as cli_mod
    from radar.models_radar.collectors.huggingface import HFModelData

    _write_model_seed(tmp_path, """\
  - id: context-model
    name: Context-7B
    family: Context
    hf_repo: org/context
    params_total: 7000000000
    context_length: 131072
    spec_verified: true
""")

    async def fake_fetch(repo, client):
        return HFModelData(params_total=7_000_000_000, context_length=163840)

    monkeypatch.setattr(cli_mod, "_verify_fetch_hf_model", fake_fetch, raising=False)

    runner = CliRunner()
    result = runner.invoke(cli_mod.app, ["models", "verify", "--root", str(tmp_path), "--check"])
    assert result.exit_code == 0, result.stdout
    assert "DRIFT" not in result.stdout
    # Rich may wrap the line at the console width, so check the pieces rather
    # than one contiguous substring.
    assert "note context-model: context_length seed=131072 vs config" in result.stdout
    assert "max_position_embeddings=163840" in result.stdout


def test_models_verify_out_of_band_ratio_is_neutral_investigate_note(
    tmp_path: Path, monkeypatch
):
    """A mismatch far outside the packed-quant band (e.g. a since-renamed repo
    or a fetch pointed at the wrong model) must not be mislabeled as a
    "packed-quant artifact" — that asserts a false cause. It's reported as a
    neutral note instead, and still never DRIFT."""
    import radar.cli as cli_mod
    from radar.models_radar.collectors.huggingface import HFModelData

    _write_model_seed(tmp_path, """\
  - id: mismatched-model
    name: Mismatched-35B
    family: Mismatched
    hf_repo: org/mismatched
    params_total: 35000000000
    spec_verified: true
""")

    async def fake_fetch(repo, client):
        return HFModelData(params_total=665_000)  # ratio ~52631x, matches hf-ornith-1-0-35b's order of magnitude

    monkeypatch.setattr(cli_mod, "_verify_fetch_hf_model", fake_fetch, raising=False)

    runner = CliRunner()
    result = runner.invoke(cli_mod.app, ["models", "verify", "--root", str(tmp_path), "--check"])
    assert result.exit_code == 0, result.stdout
    assert "DRIFT" not in result.stdout
    assert "packed-quant" not in result.stdout
    assert "note mismatched-model: params_total differs by" in result.stdout
    assert "— investigate" in result.stdout
