"""Shared template context for the dashboard device picker (single source of truth)."""

from __future__ import annotations

from typing import Any

from radar.models_radar.device_fit import TIGHT_FRACTION, evaluate_fit
from radar.models_radar.devices import (
    CLUSTER_PRESETS,
    COMMON_DEVICE_TIERS,
    DATACENTER_DEVICE_TIERS,
    DEVICE_PRESETS,
    NODE_PRESETS,
    USABLE_FRACTION,
    resolve_device,
    usable_memory_gb,
)
from radar.models_radar.entities import ModelEntry


def picker_context() -> dict[str, Any]:
    """Presets + usable fractions for the Models-page device picker."""
    device_presets = [
        {"id": key, "label": d.name, "total_memory_gb": d.total_memory_gb,
         "kind": d.kind, "gpu_count": d.gpu_count, "usable_gb": usable_memory_gb(d),
         "datacenter": d.datacenter}
        for key, d in DEVICE_PRESETS.items()
    ]
    node_and_cluster_presets = [
        {"id": key, "label": d.name, "total_memory_gb": d.total_memory_gb,
         "kind": d.kind, "gpu_count": d.gpu_count, "usable_gb": usable_memory_gb(d),
         "datacenter": True}
        for key, d in {**NODE_PRESETS, **CLUSTER_PRESETS}.items()
    ]
    return {
        "device_presets": device_presets + node_and_cluster_presets,
        "usable_fraction": dict(USABLE_FRACTION),
        "tight_fraction": TIGHT_FRACTION,
    }


def fit_by_tier(model: ModelEntry) -> list[dict[str, Any]]:
    """Largest-fitting quant per common device tier (for the per-model page)."""
    rows: list[dict[str, Any]] = []
    for key in COMMON_DEVICE_TIERS:
        dev = DEVICE_PRESETS[key]
        fit = evaluate_fit(model, dev)
        rows.append({"device": dev.name, "verdict": fit.verdict,
                     "best_quant": fit.best_quant_format or "-"})
    return rows


def datacenter_fit_rows(model: ModelEntry) -> list[dict[str, Any]]:
    """Largest-fitting quant per datacenter-class device/node (second "Runs on" table)."""
    rows: list[dict[str, Any]] = []
    for key in DATACENTER_DEVICE_TIERS:
        dev = resolve_device(key)
        fit = evaluate_fit(model, dev)
        rows.append({"device": dev.name, "verdict": fit.verdict,
                     "best_quant": fit.best_quant_format or "-"})
    return rows
