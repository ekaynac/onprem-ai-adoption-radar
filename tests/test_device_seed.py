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
