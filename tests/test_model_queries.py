from __future__ import annotations

from pathlib import Path

from radar.mcp_server.model_queries import ModelQueryService
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


def test_get_model_returns_full_with_quants(tmp_path: Path):
    _seed(tmp_path)
    svc = ModelQueryService(tmp_path)
    m = svc.get_model("qwen3-8b")
    assert m is not None and m["id"] == "qwen3-8b"
    assert m["quants"] and m["quants"][0]["format"] == "Q4_K_M"
    assert svc.get_model("nope") is None


def test_no_model_run_returns_empty(tmp_path: Path):
    (tmp_path / "data").mkdir(parents=True)
    svc = ModelQueryService(tmp_path)
    assert svc.list_models() == [] and svc.get_model("x") is None


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
