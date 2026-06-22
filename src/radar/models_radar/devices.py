"""Device profiles + usable-memory model for hardware-fit checks.

Usable fractions are the ecosystem-standard fudge factors (dedicated GPU 0.85,
Apple unified memory 0.72, CPU 0.50) that account for OS/runtime/CUDA overhead.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class DeviceError(ValueError):
    """Raised when a device spec cannot be resolved."""


USABLE_FRACTION: dict[str, float] = {"gpu": 0.85, "apple": 0.72, "cpu": 0.50}


class DeviceProfile(BaseModel):
    """A machine the user might run models on."""

    model_config = ConfigDict(frozen=True)

    name: str
    kind: Literal["gpu", "apple", "cpu"]
    total_memory_gb: float
    gpu_count: int = 1


def usable_memory_gb(device: DeviceProfile) -> float:
    """Memory actually available to the model (GB), after the kind's fraction."""
    return round(device.total_memory_gb * USABLE_FRACTION[device.kind] * device.gpu_count, 2)


def _gpu(name: str, gb: float, count: int = 1) -> DeviceProfile:
    return DeviceProfile(name=name, kind="gpu", total_memory_gb=gb, gpu_count=count)


def _mac(name: str, gb: float) -> DeviceProfile:
    return DeviceProfile(name=name, kind="apple", total_memory_gb=gb)


DEVICE_PRESETS: dict[str, DeviceProfile] = {
    "rtx-4060-8gb": _gpu("RTX 4060 (8GB)", 8),
    "rtx-4070-12gb": _gpu("RTX 4070 (12GB)", 12),
    "rtx-4080-16gb": _gpu("RTX 4080 (16GB)", 16),
    "rtx-4090-24gb": _gpu("RTX 4090 (24GB)", 24),
    "rtx-5090-32gb": _gpu("RTX 5090 (32GB)", 32),
    "rtx-6000-ada-48gb": _gpu("RTX 6000 Ada (48GB)", 48),
    "a100-40gb": _gpu("A100 (40GB)", 40),
    "a100-80gb": _gpu("A100 (80GB)", 80),
    "h100-80gb": _gpu("H100 (80GB)", 80),
    "h200-141gb": _gpu("H200 (141GB)", 141),
    "mi300x-192gb": _gpu("MI300X (192GB)", 192),
    "2x-a100-80gb": _gpu("2x A100 (80GB)", 80, count=2),
    "mac-16gb": _mac("Mac (16GB unified)", 16),
    "mac-32gb": _mac("Mac (32GB unified)", 32),
    "mac-64gb": _mac("Mac (64GB unified)", 64),
    "mac-128gb": _mac("Mac (128GB unified)", 128),
    "mac-192gb": _mac("Mac (192GB unified)", 192),
    "mac-512gb": _mac("Mac Studio (512GB unified)", 512),
    "laptop-16gb-cpu": DeviceProfile(name="Laptop (16GB, no GPU)", kind="cpu", total_memory_gb=16),
}


COMMON_DEVICE_TIERS: list[str] = [
    "rtx-4060-8gb", "rtx-4080-16gb", "rtx-4090-24gb",
    "rtx-6000-ada-48gb", "a100-80gb", "mac-64gb",
]


def resolve_device(spec: str | dict[str, Any]) -> DeviceProfile:
    """A preset name, or a custom dict {kind, total_memory_gb, gpu_count?}."""
    if isinstance(spec, str):
        preset = DEVICE_PRESETS.get(spec)
        if preset is None:
            raise DeviceError(
                f"Unknown device preset '{spec}'. Known: {', '.join(sorted(DEVICE_PRESETS))}"
            )
        return preset
    try:
        return DeviceProfile(
            name=str(spec.get("name") or "custom"),
            kind=spec["kind"],
            total_memory_gb=float(spec["total_memory_gb"]),
            gpu_count=int(spec.get("gpu_count", 1)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DeviceError(f"Invalid device spec {spec!r}: {exc}") from exc
