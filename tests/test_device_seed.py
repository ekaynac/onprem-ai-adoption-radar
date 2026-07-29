"""Device seed loading (config/device-seed.yaml)."""

from __future__ import annotations

from pathlib import Path

import pytest

from radar.models_radar.device_seed import DeviceSeedError, load_device_seed


_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_bundled_seed_loads_and_covers_legacy_presets():
    seeds = load_device_seed(_REPO_ROOT / "config" / "device-seed.yaml").devices
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
    seeds = {s.id: s for s in load_device_seed(_REPO_ROOT / "config" / "device-seed.yaml").devices}
    # b300-288gb -> b300-270gb: the brief's id baked in an invented marketing figure
    # (288GB); NVIDIA's own Blackwell technical brief gives 270GB for the HGX B300
    # per-GPU config actually used to source this row, so the id was corrected to match
    # the verified number (cardinal honest-numbers rule).
    for did in ("b300-270gb", "mi325x-256gb", "mi355x-288gb", "gaudi3-128gb",
                "ascend-910b-64gb", "8x-h200-141gb", "8x-b200-192gb",
                "8x-mi300x-192gb", "4x-h100-80gb"):
        assert did in seeds, did
        assert seeds[did].datacenter is True, did
    # rtx-pro-6000-blackwell-96gb is NVIDIA's own "Workstation Edition" — same Pro/
    # workstation tier as rtx-6000-ada-48gb (also not datacenter:true), so it is checked
    # for presence + citation but NOT asserted datacenter:true.
    rtx_pro_6000 = seeds["rtx-pro-6000-blackwell-96gb"]
    assert rtx_pro_6000.datacenter is False
    assert rtx_pro_6000.spec_url and rtx_pro_6000.verified
    h200 = seeds["h200-141gb"]
    assert h200.memory_bandwidth_gbs and h200.memory_bandwidth_gbs > 1000
    assert h200.spec_url and h200.verified


def test_every_v2_number_is_cited():
    seeds = load_device_seed(_REPO_ROOT / "config" / "device-seed.yaml").devices
    v2_fields = ("memory_bandwidth_gbs", "tflops_fp16", "tflops_fp8", "tflops_fp4",
                 "tdp_watts", "indicative_price_usd")
    for s in seeds:
        if any(getattr(s, f) is not None for f in v2_fields):
            assert s.spec_url, f"{s.id} has v2 numbers but no spec_url"
            assert s.verified, f"{s.id} has v2 numbers but no verified date"
        for f in v2_fields:
            value = getattr(s, f)
            assert value is None or value > 0, f"{s.id}.{f} must be positive"


def test_nodes_and_clusters_load_and_resolve():
    catalog = load_device_seed(_REPO_ROOT / "config" / "device-seed.yaml")
    nodes = {n.id: n for n in catalog.nodes}
    assert nodes["hgx-h200-8"].gpus_per_node == 8
    assert nodes["hgx-h200-8"].device == "h200-141gb"
    assert nodes["gb200-nvl72"].gpus_per_node == 72
    assert nodes["gb300-nvl72"].gpus_per_node == 72
    assert nodes["gb300-nvl72"].device == "b300-270gb"
    clusters = {c.id: c for c in catalog.clusters}
    assert clusters["2x-hgx-h200-8"].node == "hgx-h200-8"


def test_node_ref_integrity(tmp_path: Path):
    p = tmp_path / "d.yaml"
    p.write_text(
        "devices:\n  - {id: g, name: G, kind: gpu, total_memory_gb: 80}\n"
        "nodes:\n  - {id: n, name: N, device: missing, gpus_per_node: 8}\n",
        encoding="utf-8",
    )
    with pytest.raises(DeviceSeedError, match="unknown device"):
        load_device_seed(p)
