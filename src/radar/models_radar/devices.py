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


def _cpu(name: str, gb: float) -> DeviceProfile:
    return DeviceProfile(name=name, kind="cpu", total_memory_gb=gb)


DEVICE_PRESETS: dict[str, DeviceProfile] = {
    # Consumer NVIDIA
    "rtx-3060-12gb": _gpu("RTX 3060 (12GB)", 12),
    "rtx-3080-10gb": _gpu("RTX 3080 (10GB)", 10),
    "rtx-3090-24gb": _gpu("RTX 3090 (24GB)", 24),
    "rtx-4060-8gb": _gpu("RTX 4060 (8GB)", 8),
    "rtx-4060-ti-16gb": _gpu("RTX 4060 Ti (16GB)", 16),
    "rtx-4070-12gb": _gpu("RTX 4070 (12GB)", 12),
    "rtx-4070-ti-super-16gb": _gpu("RTX 4070 Ti Super (16GB)", 16),
    "rtx-4080-16gb": _gpu("RTX 4080 (16GB)", 16),
    "rtx-4090-24gb": _gpu("RTX 4090 (24GB)", 24),
    "rtx-5070-12gb": _gpu("RTX 5070 (12GB)", 12),
    "rtx-5070-ti-16gb": _gpu("RTX 5070 Ti (16GB)", 16),
    "rtx-5080-16gb": _gpu("RTX 5080 (16GB)", 16),
    "rtx-5090-32gb": _gpu("RTX 5090 (32GB)", 32),
    # Pro / workstation NVIDIA
    "rtx-a6000-48gb": _gpu("RTX A6000 (48GB)", 48),
    "rtx-6000-ada-48gb": _gpu("RTX 6000 Ada (48GB)", 48),
    "a10-24gb": _gpu("A10 (24GB)", 24),
    "a40-48gb": _gpu("A40 (48GB)", 48),
    "l4-24gb": _gpu("L4 (24GB)", 24),
    "l40s-48gb": _gpu("L40S (48GB)", 48),
    "t4-16gb": _gpu("T4 (16GB)", 16),
    "v100-32gb": _gpu("V100 (32GB)", 32),
    # Datacenter NVIDIA
    "a100-40gb": _gpu("A100 (40GB)", 40),
    "a100-80gb": _gpu("A100 (80GB)", 80),
    "h100-80gb": _gpu("H100 (80GB)", 80),
    "h100-nvl-94gb": _gpu("H100 NVL (94GB)", 94),
    "h200-141gb": _gpu("H200 (141GB)", 141),
    "gh200-96gb": _gpu("GH200 (96GB)", 96),
    "b200-192gb": _gpu("B200 (192GB)", 192),
    # AMD
    "mi210-64gb": _gpu("MI210 (64GB)", 64),
    "mi250-128gb": _gpu("MI250 (128GB)", 128),
    "mi300x-192gb": _gpu("MI300X (192GB)", 192),
    # Multi-GPU rigs
    "2x-rtx-4090-24gb": _gpu("2x RTX 4090 (24GB)", 24, count=2),
    "4x-rtx-4090-24gb": _gpu("4x RTX 4090 (24GB)", 24, count=4),
    "2x-a100-80gb": _gpu("2x A100 (80GB)", 80, count=2),
    "4x-a100-80gb": _gpu("4x A100 (80GB)", 80, count=4),
    "8x-h100-80gb": _gpu("8x H100 (80GB)", 80, count=8),
    # Apple unified memory
    "mac-16gb": _mac("Mac (16GB unified)", 16),
    "mac-24gb": _mac("Mac (24GB unified)", 24),
    "mac-32gb": _mac("Mac (32GB unified)", 32),
    "mac-48gb": _mac("Mac (48GB unified)", 48),
    "mac-64gb": _mac("Mac (64GB unified)", 64),
    "mac-96gb": _mac("Mac (96GB unified)", 96),
    "mac-128gb": _mac("Mac (128GB unified)", 128),
    "mac-192gb": _mac("Mac (192GB unified)", 192),
    "mac-256gb": _mac("Mac Studio (256GB unified)", 256),
    "mac-512gb": _mac("Mac Studio (512GB unified)", 512),
    # CPU / system RAM
    "laptop-16gb-cpu": _cpu("Laptop (16GB, no GPU)", 16),
    "workstation-64gb-cpu": _cpu("Workstation (64GB RAM, no GPU)", 64),
    "server-256gb-cpu": _cpu("Server (256GB RAM, no GPU)", 256),
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
