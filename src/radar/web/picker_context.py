"""Shared template context for the dashboard device picker (single source of truth)."""

from __future__ import annotations

from typing import Any

from radar.models_radar.devices import DEVICE_PRESETS, USABLE_FRACTION, usable_memory_gb


def picker_context() -> dict[str, Any]:
    """Presets + usable fractions for the Models-page device picker."""
    return {
        "device_presets": [
            {"id": key, "label": d.name, "total_memory_gb": d.total_memory_gb,
             "kind": d.kind, "gpu_count": d.gpu_count, "usable_gb": usable_memory_gb(d)}
            for key, d in DEVICE_PRESETS.items()
        ],
        "usable_fraction": dict(USABLE_FRACTION),
    }
