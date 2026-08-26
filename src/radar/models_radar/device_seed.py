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
    manufacturer: str | None = None  # chip maker (NVIDIA, AMD, Apple...)

    def to_profile(self) -> DeviceProfile:
        from radar.models_radar.devices import DeviceProfile  # local: avoid cycle

        return DeviceProfile(**self.model_dump(exclude={"id"}))


class NodeSeed(BaseModel):
    """A multi-GPU node (e.g. an HGX/OAM baseboard) in config/device-seed.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    device: str  # ref into devices
    gpus_per_node: int
    interconnect: str | None = None
    spec_url: str | None = None
    verified: str | None = None
    vendor: str | None = None  # system builder (NVIDIA, Dell, HPE, Advantech...)
    tdp_watts: int | None = None
    indicative_price_usd: int | None = None
    datacenter: bool | None = None  # None = default (True for baseboards)
    # Integrated/system devices (e.g. DGX Spark's GB10) carry their own
    # bandwidth/compute specs at node level.
    memory_bandwidth_gbs: float | None = None
    tflops_fp4: float | None = None


class ClusterSeed(BaseModel):
    """A multi-node cluster (e.g. a SuperPOD rack group) in config/device-seed.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    node: str  # ref into nodes
    node_count: int
    fabric: str | None = None
    spec_url: str | None = None
    verified: str | None = None


class DeviceCatalog(BaseModel):
    """The full parsed device seed: devices, nodes, and clusters."""

    model_config = ConfigDict(frozen=True)

    devices: list[DeviceSeed]
    nodes: list[NodeSeed]
    clusters: list[ClusterSeed]


def load_device_seed(path: Path) -> DeviceCatalog:
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
        devices = [DeviceSeed.model_validate(item) for item in raw.get("devices") or []]
        nodes = [NodeSeed.model_validate(item) for item in raw.get("nodes") or []]
        clusters = [ClusterSeed.model_validate(item) for item in raw.get("clusters") or []]
    except ValidationError as exc:
        raise DeviceSeedError(f"Device seed validation failed for {path}: {exc}") from exc
    _check_ids(devices, path)
    _check_ref_integrity(devices, nodes, clusters, path)
    return DeviceCatalog(devices=devices, nodes=nodes, clusters=clusters)


def _check_ids(seeds: list[DeviceSeed], path: Path) -> None:
    """Unique, non-empty ids."""
    ids = [s.id for s in seeds]
    if any(not i for i in ids):
        raise DeviceSeedError(f"Device seed {path} has an empty id")
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise DeviceSeedError(f"Duplicate device ids in {path}: {', '.join(duplicates)}")


def _check_ref_integrity(
    devices: list[DeviceSeed],
    nodes: list[NodeSeed],
    clusters: list[ClusterSeed],
    path: Path,
) -> None:
    """node.device must exist in devices; cluster.node must exist in nodes."""
    device_ids = {d.id for d in devices}
    for node in nodes:
        if node.device not in device_ids:
            raise DeviceSeedError(
                f"Device seed {path}: node {node.id!r} references unknown device "
                f"{node.device!r}"
            )
    node_ids = {n.id for n in nodes}
    for cluster in clusters:
        if cluster.node not in node_ids:
            raise DeviceSeedError(
                f"Device seed {path}: cluster {cluster.id!r} references unknown node "
                f"{cluster.node!r}"
            )
