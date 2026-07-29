"""Load the bundled device seed (config/device-seed.yaml)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError


if TYPE_CHECKING:
    from radar.models_radar.devices import DeviceProfile


class DeviceSeedError(ValueError):
    """Raised when the device seed cannot be loaded."""


class DeviceSeed(BaseModel):
    """One device entry in config/device-seed.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    kind: str  # validated by DeviceProfile's Literal on conversion
    total_memory_gb: float
    gpu_count: int = 1
    memory_bandwidth_gbs: float | None = None
    tflops_fp16: float | None = None
    tflops_fp8: float | None = None
    tflops_fp4: float | None = None
    interconnect: str | None = None
    tdp_watts: int | None = None
    indicative_price_usd: int | None = None
    spec_url: str | None = None
    verified: str | None = None
    datacenter: bool = False

    def to_profile(self) -> DeviceProfile:
        from radar.models_radar.devices import DeviceProfile  # local: avoid cycle

        return DeviceProfile(**self.model_dump(exclude={"id"}))


def load_device_seed(path: Path) -> list[DeviceSeed]:
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DeviceSeedError(f"Device seed not found: {path}") from exc
    try:
        raw = yaml.safe_load(contents) or {}
    except yaml.YAMLError as exc:
        raise DeviceSeedError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise DeviceSeedError(f"Device seed {path} must be a mapping with a 'devices' list")
    try:
        seeds = [DeviceSeed.model_validate(item) for item in raw.get("devices") or []]
    except ValidationError as exc:
        raise DeviceSeedError(f"Device seed validation failed for {path}: {exc}") from exc
    _check_ids(seeds, path)
    return seeds


def _check_ids(seeds: list[DeviceSeed], path: Path) -> None:
    """Unique, non-empty ids."""
    ids = [s.id for s in seeds]
    if any(not i for i in ids):
        raise DeviceSeedError(f"Device seed {path} has an empty id")
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise DeviceSeedError(f"Duplicate device ids in {path}: {', '.join(duplicates)}")
