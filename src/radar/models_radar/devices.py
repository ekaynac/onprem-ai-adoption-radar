"""Device profiles + usable-memory model for hardware-fit checks.

Usable fractions are the ecosystem-standard fudge factors (dedicated GPU 0.85,
Apple unified memory 0.72, CPU 0.50) that account for OS/runtime/CUDA overhead.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict


if TYPE_CHECKING:
    from radar.models_radar.device_seed import DeviceCatalog


class DeviceError(ValueError):
    """Raised when a device spec cannot be resolved."""


# "unified" = non-Apple unified-memory SoCs (Grace-Blackwell GB10/GB300
# desktops, Jetson, Ryzen AI Max): the model shares one pool with the
# OS and CPU, so the Apple fraction applies rather than the dGPU one.
USABLE_FRACTION: dict[str, float] = {
    "gpu": 0.85,
    "apple": 0.72,
    "unified": 0.72,
    "cpu": 0.50,
}


class DeviceProfile(BaseModel):
    """A machine the user might run models on."""

    model_config = ConfigDict(frozen=True)

    name: str
    kind: Literal["gpu", "apple", "unified", "cpu"]
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
    verified: str | None = None  # ISO date
    datacenter: bool = False
    # Taxonomy (H1): `manufacturer` is the CHIP maker (NVIDIA, AMD,
    # Apple, Intel); `vendor` is the SYSTEM builder (NVIDIA, Dell, HPE,
    # Advantech, Framework...) — set when this profile is a flattened
    # node/cluster; `chip` then names the contained device id.
    manufacturer: str | None = None
    vendor: str | None = None
    chip: str | None = None


def usable_memory_gb(device: DeviceProfile) -> float:
    """Memory actually available to the model (GB), after the kind's fraction."""
    return round(device.total_memory_gb * USABLE_FRACTION[device.kind] * device.gpu_count, 2)


def _bundled_seed_path() -> Path:
    # Repo-root config; same resolution idiom as the model/technique seeds.
    return Path(__file__).resolve().parents[3] / "config" / "device-seed.yaml"


def _load_catalog() -> DeviceCatalog:
    from radar.models_radar.device_seed import load_device_seed  # local: avoid cycle

    return load_device_seed(_bundled_seed_path())


_CATALOG: DeviceCatalog = _load_catalog()


DEVICE_PRESETS: dict[str, DeviceProfile] = {s.id: s.to_profile() for s in _CATALOG.devices}


def _flatten_nodes(catalog: DeviceCatalog) -> dict[str, DeviceProfile]:
    """Node = its base device, with per-node overrides layered on top."""
    devices_by_id = {d.id: d for d in catalog.devices}
    presets: dict[str, DeviceProfile] = {}
    for node in catalog.nodes:
        base = devices_by_id[node.device].to_profile()
        presets[node.id] = base.model_copy(
            update={
                "name": node.name,
                "gpu_count": node.gpus_per_node,
                "interconnect": node.interconnect or base.interconnect,
                # Reference baseboards default to datacenter; a vendor
                # system states its own class (a DGX Spark or an edge box
                # is not a rack part).
                "datacenter": (
                    node.datacenter if node.datacenter is not None else True
                ),
                "vendor": node.vendor,
                "chip": node.device,
                "spec_url": node.spec_url or base.spec_url,
                "verified": node.verified or base.verified,
                "tdp_watts": node.tdp_watts or base.tdp_watts,
                "indicative_price_usd": (
                    node.indicative_price_usd or base.indicative_price_usd
                ),
            }
        )
    return presets


def _flatten_clusters(
    catalog: DeviceCatalog, node_presets: dict[str, DeviceProfile]
) -> dict[str, DeviceProfile]:
    """Cluster = its base node, gpu_count multiplied by node_count, interconnect = fabric."""
    nodes_by_id = {n.id: n for n in catalog.nodes}
    presets: dict[str, DeviceProfile] = {}
    for cluster in catalog.clusters:
        node = nodes_by_id[cluster.node]
        base = node_presets[cluster.node]
        presets[cluster.id] = base.model_copy(
            update={
                "name": cluster.name,
                "gpu_count": node.gpus_per_node * cluster.node_count,
                "interconnect": cluster.fabric,
                "datacenter": True,
            }
        )
    return presets


NODE_PRESETS: dict[str, DeviceProfile] = _flatten_nodes(_CATALOG)
CLUSTER_PRESETS: dict[str, DeviceProfile] = _flatten_clusters(_CATALOG, NODE_PRESETS)


COMMON_DEVICE_TIERS: list[str] = [
    "rtx-4060-8gb", "rtx-4080-16gb", "rtx-4090-24gb",
    "rtx-6000-ada-48gb", "a100-80gb", "mac-64gb",
]


# Datacenter-class "Runs on" row set for the second per-model table (sub-project C).
# gb300-nvl72 exists in the catalog but is deliberately left out here — this list
# stays at 6 rows; it remains picker/MCP-visible via NODE_PRESETS.
DATACENTER_DEVICE_TIERS: list[str] = [
    "h100-80gb", "h200-141gb", "b200-192gb",
    "mi300x-192gb", "hgx-h200-8", "gb200-nvl72",
]


def resolve_device(spec: str | dict[str, Any]) -> DeviceProfile:
    """A preset name, or a custom dict {kind, total_memory_gb, gpu_count?}."""
    if isinstance(spec, str):
        preset = (
            DEVICE_PRESETS.get(spec) or NODE_PRESETS.get(spec) or CLUSTER_PRESETS.get(spec)
        )
        if preset is None:
            known = sorted(DEVICE_PRESETS) + sorted(NODE_PRESETS) + sorted(CLUSTER_PRESETS)
            raise DeviceError(
                f"Unknown device preset '{spec}'. Known devices/nodes/clusters: "
                f"{', '.join(known)}"
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
