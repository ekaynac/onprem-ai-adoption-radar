"""Query service backing the model-radar MCP tools (read-only over run state)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from radar.models_radar.device_fit import evaluate_fit
from radar.models_radar.device_fit import fit_report as _fit_report
from radar.models_radar.devices import DEVICE_PRESETS, resolve_device, usable_memory_gb
from radar.models_radar.entities import ModelEntry
from radar.models_radar.history import load_model_events
from radar.models_radar.memory import minimum_viable_quant
from radar.models_radar.momentum import compute_model_momentum
from radar.storage.model_metrics_store import ModelMetricsStore
from radar.storage.run_store import RunStore


def _latest_model_cards(root: Path) -> list[dict[str, Any]]:
    """Raw model_cards.json dicts from the latest kind==models run; [] if none."""
    runs_dir = root / "data" / "runs"
    if not runs_dir.exists():
        return []
    run_store = RunStore(runs_dir)
    for rid in reversed(run_store.list_runs()):
        if run_store.read_meta(rid).get("kind") == "models":
            path = run_store._run_dir(rid) / "model_cards.json"
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
    return []


class ModelQueryService:
    """Transport-agnostic queries over the latest model scan."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.db_path = self.root / "data" / "radar.db"
        self.history_path = self.root / "data" / "model-history.jsonl"

    def _entries(self) -> list[ModelEntry]:
        return [ModelEntry.model_validate(c) for c in _latest_model_cards(self.root)]

    def list_models(
        self,
        max_memory_gb: float | None = None,
        hardware_tier: str | None = None,
        family: str | None = None,
        modality: str | None = None,
        detail: str = "compact",
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for entry in self._entries():
            if hardware_tier and entry.hardware_tier.value != hardware_tier.lower():
                continue
            if family and entry.family.lower() != family.lower():
                continue
            if modality and entry.modality.value != modality.lower():
                continue
            if max_memory_gb is not None:
                mv = minimum_viable_quant(entry.quants)
                if mv is None or mv.est_memory_gb_4k is None or mv.est_memory_gb_4k > max_memory_gb:
                    continue
            rows.append(_model_compact(entry) if detail == "compact" else _model_full(entry))
        return rows

    def get_model(self, model_id: str) -> dict[str, Any] | None:
        entry = next((e for e in self._entries() if e.id == model_id), None)
        if entry is None:
            return None
        data = _model_full(entry)
        store = ModelMetricsStore(self.db_path)
        store.initialize()
        events = [e for e in load_model_events(self.history_path) if e.model_id == model_id]
        data["history"] = [
            {"change_type": e.change_type.value, "ring": e.ring.value,
             "previous_ring": e.previous_ring.value if e.previous_ring else None,
             "observed_at": e.observed_at.isoformat()}
            for e in events
        ]
        mom = compute_model_momentum(model_id, store.history_for(model_id), events)
        data["momentum"] = {"direction": mom.direction,
                            "downloads_growth_pct": mom.downloads_growth_pct}
        return data

    def list_devices(self) -> list[dict[str, Any]]:
        return [
            {"id": key, "name": d.name, "kind": d.kind,
             "total_memory_gb": d.total_memory_gb, "gpu_count": d.gpu_count,
             "usable_gb": usable_memory_gb(d)}
            for key, d in DEVICE_PRESETS.items()
        ]

    def can_run(self, model_id: str, device: str | dict[str, Any],
                context_tokens: int = 4096) -> dict[str, Any] | None:
        entry = next((e for e in self._entries() if e.id == model_id), None)
        if entry is None:
            return None
        return evaluate_fit(entry, resolve_device(device), context_tokens).model_dump(mode="json")

    def device_fit_report(self, device: str | dict[str, Any],
                          context_tokens: int = 4096) -> list[dict[str, Any]]:
        dev = resolve_device(device)
        return [f.model_dump(mode="json") for f in _fit_report(self._entries(), dev, context_tokens)]

    def model_movers(self) -> list[dict[str, Any]]:
        store = ModelMetricsStore(self.db_path)
        store.initialize()
        all_events = load_model_events(self.history_path)
        by_model: dict[str, list] = {}
        for ev in all_events:
            by_model.setdefault(ev.model_id, []).append(ev)
        movers: list[dict[str, Any]] = []
        for entry in self._entries():
            mom = compute_model_momentum(
                entry.id, store.history_for(entry.id), by_model.get(entry.id, []))
            if mom.direction != "steady":
                movers.append({"id": entry.id, "direction": mom.direction,
                               "downloads_growth_pct": mom.downloads_growth_pct,
                               "note": mom.note})
        return movers


def _model_compact(entry: ModelEntry) -> dict[str, Any]:
    mv = minimum_viable_quant(entry.quants)
    return {
        "id": entry.id, "name": entry.name, "family": entry.family,
        "ring": entry.ring.value if entry.ring else None,
        "hardware_tier": entry.hardware_tier.value,
        "min_memory_gb": mv.est_memory_gb_4k if mv else None,
        "params_total": entry.params_total, "modality": entry.modality.value,
    }


def _model_full(entry: ModelEntry) -> dict[str, Any]:
    data = entry.model_dump(mode="json")
    mv = minimum_viable_quant(entry.quants)
    data["min_memory_gb"] = mv.est_memory_gb_4k if mv else None
    return data
