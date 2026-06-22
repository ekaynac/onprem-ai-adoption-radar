from __future__ import annotations

import pytest
from pydantic import ValidationError

from radar.models_radar.devices import (
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
