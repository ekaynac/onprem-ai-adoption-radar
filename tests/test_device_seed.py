"""Device seed loading (config/device-seed.yaml)."""

from __future__ import annotations

from pathlib import Path

import pytest

from radar.models_radar.device_seed import DeviceSeedError, load_device_seed


_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_bundled_seed_loads_and_covers_legacy_presets():
    seeds = load_device_seed(_REPO_ROOT / "config" / "device-seed.yaml")
    by_id = {s.id: s for s in seeds}
    assert len(seeds) >= 48
    assert by_id["rtx-4090-24gb"].total_memory_gb == 24
    assert by_id["mac-64gb"].kind == "apple"
    assert by_id["8x-h100-80gb"].gpu_count == 8
    assert by_id["server-256gb-cpu"].kind == "cpu"


def test_duplicate_ids_rejected(tmp_path: Path):
    p = tmp_path / "d.yaml"
    p.write_text(
        "devices:\n"
        "  - {id: a, name: A, kind: gpu, total_memory_gb: 8}\n"
        "  - {id: a, name: A2, kind: gpu, total_memory_gb: 16}\n",
        encoding="utf-8",
    )
    with pytest.raises(DeviceSeedError, match="Duplicate"):
        load_device_seed(p)


def test_missing_file_and_bad_yaml_raise(tmp_path: Path):
    with pytest.raises(DeviceSeedError, match="not found"):
        load_device_seed(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("devices: [:::", encoding="utf-8")
    with pytest.raises(DeviceSeedError, match="Invalid YAML"):
        load_device_seed(bad)


def test_unknown_field_rejected(tmp_path: Path):
    p = tmp_path / "d.yaml"
    p.write_text(
        "devices:\n  - {id: a, name: A, kind: gpu, total_memory_gb: 8, bogus: 1}\n",
        encoding="utf-8",
    )
    with pytest.raises(DeviceSeedError, match="validation failed"):
        load_device_seed(p)


def test_new_datacenter_devices_present_with_cited_specs():
    seeds = {s.id: s for s in load_device_seed(_REPO_ROOT / "config" / "device-seed.yaml")}
    for did in ("b300-288gb", "mi325x-256gb", "mi355x-288gb", "gaudi3-128gb",
                "ascend-910b-64gb", "rtx-pro-6000-blackwell-96gb",
                "8x-h200-141gb", "8x-b200-192gb", "8x-mi300x-192gb", "4x-h100-80gb"):
        assert did in seeds, did
        assert seeds[did].datacenter is True, did
    h200 = seeds["h200-141gb"]
    assert h200.memory_bandwidth_gbs and h200.memory_bandwidth_gbs > 1000
    assert h200.spec_url and h200.verified


def test_every_v2_number_is_cited():
    seeds = load_device_seed(_REPO_ROOT / "config" / "device-seed.yaml")
    v2_fields = ("memory_bandwidth_gbs", "tflops_fp16", "tflops_fp8", "tflops_fp4",
                 "tdp_watts", "indicative_price_usd")
    for s in seeds:
        if any(getattr(s, f) is not None for f in v2_fields):
            assert s.spec_url, f"{s.id} has v2 numbers but no spec_url"
            assert s.verified, f"{s.id} has v2 numbers but no verified date"
        for f in v2_fields:
            value = getattr(s, f)
            assert value is None or value > 0, f"{s.id}.{f} must be positive"
