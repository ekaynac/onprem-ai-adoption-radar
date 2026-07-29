from __future__ import annotations

import pytest
from pydantic import ValidationError

from radar.models_radar.devices import (
    COMMON_DEVICE_TIERS,
    DEVICE_PRESETS,
    DeviceError,
    DeviceProfile,
    resolve_device,
    usable_memory_gb,
)


def test_usable_memory_by_kind():
    assert usable_memory_gb(DeviceProfile(name="g", kind="gpu", total_memory_gb=24)) == pytest.approx(20.4)
    assert usable_memory_gb(DeviceProfile(name="m", kind="apple", total_memory_gb=64)) == pytest.approx(46.08)
    assert usable_memory_gb(DeviceProfile(name="c", kind="cpu", total_memory_gb=32)) == pytest.approx(16.0)


def test_usable_memory_multi_gpu():
    d = DeviceProfile(name="2xa100", kind="gpu", total_memory_gb=80, gpu_count=2)
    assert usable_memory_gb(d) == pytest.approx(136.0)  # 80 * 0.85 * 2


def test_presets_include_common_devices():
    assert "rtx-4090-24gb" in DEVICE_PRESETS
    assert "mac-64gb" in DEVICE_PRESETS and DEVICE_PRESETS["mac-64gb"].kind == "apple"
    assert DEVICE_PRESETS["a100-80gb"].total_memory_gb == 80
    assert DEVICE_PRESETS["2x-a100-80gb"].gpu_count == 2


def test_resolve_preset_and_custom():
    assert resolve_device("rtx-4090-24gb").total_memory_gb == 24
    custom = resolve_device({"kind": "gpu", "total_memory_gb": 12})
    assert custom.kind == "gpu" and custom.total_memory_gb == 12 and custom.gpu_count == 1


def test_resolve_bad_spec_raises():
    with pytest.raises(DeviceError):
        resolve_device("no-such-preset")
    with pytest.raises(DeviceError):
        resolve_device({"kind": "gpu"})  # missing total_memory_gb


def test_device_profile_is_frozen():
    d = DeviceProfile(name="g", kind="gpu", total_memory_gb=24)
    with pytest.raises(ValidationError):
        d.total_memory_gb = 48


def test_expanded_presets_resolve_and_count():
    assert len(DEVICE_PRESETS) >= 45
    # spot-check new kinds + usable math
    assert usable_memory_gb(DEVICE_PRESETS["rtx-3090-24gb"]) == 20.4
    assert usable_memory_gb(DEVICE_PRESETS["8x-h100-80gb"]) == round(80 * 0.85 * 8, 2)
    assert usable_memory_gb(DEVICE_PRESETS["mac-96gb"]) == round(96 * 0.72, 2)
    assert usable_memory_gb(DEVICE_PRESETS["server-256gb-cpu"]) == round(256 * 0.5, 2)


def test_common_tiers_all_present():
    assert all(k in DEVICE_PRESETS for k in COMMON_DEVICE_TIERS)


def test_yaml_migration_preserves_every_legacy_preset():
    """The YAML seed must reproduce the pre-migration catalog exactly."""
    legacy = {
        "rtx-3060-12gb": ("gpu", 12, 1), "rtx-3080-10gb": ("gpu", 10, 1),
        "rtx-3090-24gb": ("gpu", 24, 1), "rtx-4060-8gb": ("gpu", 8, 1),
        "rtx-4060-ti-16gb": ("gpu", 16, 1), "rtx-4070-12gb": ("gpu", 12, 1),
        "rtx-4070-ti-super-16gb": ("gpu", 16, 1), "rtx-4080-16gb": ("gpu", 16, 1),
        "rtx-4090-24gb": ("gpu", 24, 1), "rtx-5070-12gb": ("gpu", 12, 1),
        "rtx-5070-ti-16gb": ("gpu", 16, 1), "rtx-5080-16gb": ("gpu", 16, 1),
        "rtx-5090-32gb": ("gpu", 32, 1), "rtx-a6000-48gb": ("gpu", 48, 1),
        "rtx-6000-ada-48gb": ("gpu", 48, 1), "a10-24gb": ("gpu", 24, 1),
        "a40-48gb": ("gpu", 48, 1), "l4-24gb": ("gpu", 24, 1),
        "l40s-48gb": ("gpu", 48, 1), "t4-16gb": ("gpu", 16, 1),
        "v100-32gb": ("gpu", 32, 1), "a100-40gb": ("gpu", 40, 1),
        "a100-80gb": ("gpu", 80, 1), "h100-80gb": ("gpu", 80, 1),
        "h100-nvl-94gb": ("gpu", 94, 1), "h200-141gb": ("gpu", 141, 1),
        "gh200-96gb": ("gpu", 96, 1), "b200-192gb": ("gpu", 192, 1),
        "mi210-64gb": ("gpu", 64, 1), "mi250-128gb": ("gpu", 128, 1),
        "mi300x-192gb": ("gpu", 192, 1), "2x-rtx-4090-24gb": ("gpu", 24, 2),
        "4x-rtx-4090-24gb": ("gpu", 24, 4), "2x-a100-80gb": ("gpu", 80, 2),
        "4x-a100-80gb": ("gpu", 80, 4), "8x-h100-80gb": ("gpu", 80, 8),
        "mac-16gb": ("apple", 16, 1), "mac-24gb": ("apple", 24, 1),
        "mac-32gb": ("apple", 32, 1), "mac-48gb": ("apple", 48, 1),
        "mac-64gb": ("apple", 64, 1), "mac-96gb": ("apple", 96, 1),
        "mac-128gb": ("apple", 128, 1), "mac-192gb": ("apple", 192, 1),
        "mac-256gb": ("apple", 256, 1), "mac-512gb": ("apple", 512, 1),
        "laptop-16gb-cpu": ("cpu", 16, 1), "workstation-64gb-cpu": ("cpu", 64, 1),
        "server-256gb-cpu": ("cpu", 256, 1),
    }
    for key, (kind, gb, count) in legacy.items():
        d = DEVICE_PRESETS[key]
        assert (d.kind, d.total_memory_gb, d.gpu_count) == (kind, gb, count), key


def test_node_and_cluster_presets_resolve_as_devices():
    from radar.models_radar.devices import CLUSTER_PRESETS, NODE_PRESETS

    node = resolve_device("hgx-h200-8")
    assert node.gpu_count == 8 and node.total_memory_gb == 141
    assert usable_memory_gb(node) == round(141 * 0.85 * 8, 2)
    assert NODE_PRESETS["gb200-nvl72"].gpu_count == 72
    assert NODE_PRESETS["gb300-nvl72"].gpu_count == 72
    assert resolve_device("gb300-nvl72").total_memory_gb == 270

    cluster = resolve_device("2x-hgx-h200-8")
    assert cluster.gpu_count == 16
    assert "2x-hgx-h200-8" in CLUSTER_PRESETS

    with pytest.raises(DeviceError):
        resolve_device("no-such-anything")
