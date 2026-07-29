from __future__ import annotations

from pathlib import Path

from radar.mcp_server.model_queries import ModelQueryService, _latest_model_cards
from radar.models import Category, Ring
from radar.models_radar.entities import (
    ArchitectureSpec,
    AttentionKind,
    BenchmarkScore,
    HardwareTier,
    Modality,
    ModelEntry,
    Openness,
    Platform,
    QuantVariant,
    SpecProvenance,
)
from radar.storage.run_store import RunStore


def _entry(mid, tier, mem, ring, family="F"):
    return ModelEntry(
        id=mid, name=mid, family=family, params_total=8_000_000_000,
        openness=Openness.OPEN_PERMISSIVE, hardware_tier=tier, ring=ring, score=4.0,
        modality=Modality.TEXT,
        quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5, est_memory_gb_4k=mem,
                             platform=Platform.GENERIC, source="hf:x")],
    )


def _seed(tmp_path: Path):
    run_store = RunStore(tmp_path / "data" / "runs")
    rid = run_store.create_run()
    entries = [
        _entry("qwen3-8b", HardwareTier.LAPTOP, 8.0, Ring.ADOPT, "Qwen3"),
        _entry("qwen3-30b-a3b", HardwareTier.APPLE_HIGH_RAM, 22.0, Ring.ADOPT, "Qwen3"),
        _entry("big-405b", HardwareTier.DATACENTER, 240.0, Ring.WATCH, "Llama"),
    ]
    run_store.save_stage(rid, "model_cards", [e.model_dump(mode="json") for e in entries])
    run_store.update_meta(rid, {"kind": "models", "model_count": 3})


def test_list_models_compact_returns_all(tmp_path: Path):
    _seed(tmp_path)
    svc = ModelQueryService(tmp_path)
    rows = svc.list_models()
    assert {r["id"] for r in rows} == {"qwen3-8b", "qwen3-30b-a3b", "big-405b"}
    assert "ring" in rows[0] and "hardware_tier" in rows[0]


def test_list_models_filters_by_max_memory(tmp_path: Path):
    _seed(tmp_path)
    svc = ModelQueryService(tmp_path)
    rows = svc.list_models(max_memory_gb=24)
    ids = {r["id"] for r in rows}
    assert "big-405b" not in ids and "qwen3-8b" in ids and "qwen3-30b-a3b" in ids


def test_list_models_filters_by_tier_and_family(tmp_path: Path):
    _seed(tmp_path)
    svc = ModelQueryService(tmp_path)
    assert {r["id"] for r in svc.list_models(hardware_tier="laptop")} == {"qwen3-8b"}
    assert {r["id"] for r in svc.list_models(family="Qwen3")} == {"qwen3-8b", "qwen3-30b-a3b"}


def test_list_models_tier_and_modality_filters_are_case_insensitive(tmp_path: Path):
    # hardware_tier/modality should match like family does, regardless of caller casing.
    _seed(tmp_path)
    svc = ModelQueryService(tmp_path)
    assert {r["id"] for r in svc.list_models(hardware_tier="LAPTOP")} == {"qwen3-8b"}
    assert {r["id"] for r in svc.list_models(modality="Text")} == {
        "qwen3-8b", "qwen3-30b-a3b", "big-405b"
    }


def test_list_models_profile_lifts_ring_for_datacenter_first(tmp_path: Path):
    from radar.models_radar.pipeline import score_entries

    run_store = RunStore(tmp_path / "data" / "runs")
    rid = run_store.create_run()
    entry = ModelEntry(
        id="big-moe", name="Big-MoE-1T", family="Big",
        params_total=1_000_000_000_000, openness=Openness.OPEN_PERMISSIVE,
        hardware_tier=HardwareTier.SINGLE_NODE, modality=Modality.TEXT,
        quants=[QuantVariant(format="FP8", bits_per_weight=8.0, est_memory_gb_4k=600.0)],
    )
    scored = score_entries([entry])
    run_store.save_stage(rid, "model_cards", [e.model_dump(mode="json") for e in scored])
    run_store.update_meta(rid, {"kind": "models", "model_count": 1})

    svc = ModelQueryService(tmp_path)
    default_rows = svc.list_models()
    dc_rows = svc.list_models(profile="datacenter-first")

    assert default_rows[0]["ring"] != "adopt"
    assert dc_rows[0]["ring"] == "adopt"


def test_list_models_unknown_profile_raises(tmp_path: Path):
    import pytest

    from radar.models_radar.scoring import ModelProfileError

    _seed(tmp_path)
    svc = ModelQueryService(tmp_path)
    with pytest.raises(ModelProfileError):
        svc.list_models(profile="nope")


def test_get_model_returns_full_with_quants(tmp_path: Path):
    _seed(tmp_path)
    svc = ModelQueryService(tmp_path)
    m = svc.get_model("qwen3-8b")
    assert m is not None and m["id"] == "qwen3-8b"
    assert m["quants"] and m["quants"][0]["format"] == "Q4_K_M"
    assert svc.get_model("nope") is None


def test_get_model_exposes_architecture_and_provenance(tmp_path: Path):
    """Task 8: MCP get_model payload gains architecture/benchmarks/provenance."""
    run_store = RunStore(tmp_path / "data" / "runs")
    rid = run_store.create_run()
    entry = ModelEntry(
        id="m-arch", name="Arch Model", family="F",
        architecture=ArchitectureSpec(
            attention_kind=AttentionKind.MLA, kv_lora_rank=512,
            num_experts=256, experts_per_token=8,
        ),
        benchmarks=[BenchmarkScore(name="MMLU-Pro", score=0.81,
                                   source_url="https://example.com/card")],
        provenance={"params_total": SpecProvenance(source="seed", verified=True)},
    )
    run_store.save_stage(rid, "model_cards", [entry.model_dump(mode="json")])
    run_store.update_meta(rid, {"kind": "models", "model_count": 1})
    svc = ModelQueryService(tmp_path)

    payload = svc.get_model("m-arch")

    assert payload is not None
    assert payload["architecture"]["kv_lora_rank"] == 512
    assert payload["architecture"]["attention_kind"] == "mla"
    assert payload["benchmarks"][0]["name"] == "MMLU-Pro"
    assert payload["provenance"]["params_total"]["source"] == "seed"
    assert payload["provenance"]["params_total"]["verified"] is True


def test_no_model_run_returns_empty(tmp_path: Path):
    (tmp_path / "data").mkdir(parents=True)
    svc = ModelQueryService(tmp_path)
    assert svc.list_models() == [] and svc.get_model("x") is None


def test_latest_cards_skips_model_run_missing_its_stage(tmp_path: Path):
    """A crashed scan (meta written, stage missing) must not raise — fall back.

    Mirrors technique_queries._latest_technique_cards' guarded gateway (see
    test_technique_queries.py::test_latest_cards_skips_research_run_missing_its_stage):
    a newer kind="models" run without model_cards.json must not shadow the
    older, complete run's cards.
    """
    _seed(tmp_path)  # older, complete kind="models" run
    run_store = RunStore(tmp_path / "data" / "runs")
    broken_run = run_store.create_run()
    run_store.update_meta(broken_run, {"kind": "models", "model_count": 0})

    cards = _latest_model_cards(tmp_path)

    assert {c["id"] for c in cards} == {"qwen3-8b", "qwen3-30b-a3b", "big-405b"}


def test_can_run_and_fit_report(tmp_path: Path):
    _seed(tmp_path)  # existing helper: writes qwen3-8b/qwen3-30b-a3b/big-405b model_cards run
    from radar.mcp_server.model_queries import ModelQueryService
    svc = ModelQueryService(tmp_path)

    devices = svc.list_devices()
    assert any(d["id"] == "rtx-4090-24gb" for d in devices)

    one = svc.can_run("qwen3-8b", "rtx-4090-24gb")
    assert one is not None and one["verdict"] in ("fits", "fits_tight", "fits_quantized")
    assert svc.can_run("nope", "rtx-4090-24gb") is None

    report = svc.device_fit_report("laptop-16gb-cpu")
    assert {r["model_id"] for r in report} == {"qwen3-8b", "qwen3-30b-a3b", "big-405b"}
    # custom device dict
    custom = svc.device_fit_report({"kind": "gpu", "total_memory_gb": 8})
    assert all("verdict" in r for r in custom)


def _seed_model_pedigree_run(tmp_path: Path, model_ref: str) -> None:
    """Seed a research run with one technique implemented by ``model_ref``."""
    from radar.research_radar.entities import (
        ImplKind,
        OnPremImpact,
        ResolvedImplementation,
        TechniqueDomain,
        TechniqueEntry,
    )
    from radar.storage.run_store import RunStore

    entry = TechniqueEntry(
        id="spec-dec", name="Speculative Decoding", category=Category.MODEL_SERVING,
        domain=TechniqueDomain.INFERENCE, onprem_impact=OnPremImpact.REDUCES_LATENCY,
        ring=Ring.ADOPT, citation_count=1697,
        resolved_implementations=[ResolvedImplementation(kind=ImplKind.MODEL, ref=model_ref)],
    )
    store = RunStore(tmp_path / "data" / "runs")
    run_id = store.create_run()
    store.update_meta(run_id, {"kind": "research"})
    store.save_stage(run_id, "technique_cards", [entry.model_dump(mode="json")])


def test_get_model_includes_techniques(tmp_path: Path):
    _seed(tmp_path)
    _seed_model_pedigree_run(tmp_path, "qwen3-8b")
    svc = ModelQueryService(tmp_path)

    payload = svc.get_model("qwen3-8b")

    assert payload["techniques"][0]["id"] == "spec-dec"
    assert payload["techniques"][0]["ring"] == "adopt"


def test_get_model_without_research_run_has_empty_techniques(tmp_path: Path):
    _seed(tmp_path)
    svc = ModelQueryService(tmp_path)

    assert svc.get_model("qwen3-8b")["techniques"] == []
