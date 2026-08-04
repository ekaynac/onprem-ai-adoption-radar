"""Query service backing the model-radar MCP tools (read-only over run state)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from radar.models_radar.device_fit import evaluate_fit
from radar.models_radar.device_fit import fit_report as _fit_report
from radar.models_radar.devices import (
    CLUSTER_PRESETS,
    DEVICE_PRESETS,
    NODE_PRESETS,
    resolve_device,
    usable_memory_gb,
)
from radar.models_radar.entities import ModelEntry
from radar.models_radar.history import load_model_events
from radar.models_radar.memory import minimum_viable_quant
from radar.models_radar.momentum import compute_model_momentum
from radar.models_radar.platform_matrix import (
    PlatformMatrixError,
    PlatformSeed,
    load_platform_matrix,
)
from radar.models_radar.scoring import rescore_entries
from radar.storage.model_metrics_store import ModelMetricsStore
from radar.storage.run_store import RunStore


logger = logging.getLogger(__name__)


def _latest_model_cards(root: Path) -> list[dict[str, Any]]:
    """Raw model_cards.json dicts from the latest kind==models run; [] if none."""
    runs_dir = root / "data" / "runs"
    if not runs_dir.exists():
        return []
    run_store = RunStore(runs_dir)
    # NOT latest_run_of_kind: a crashed scan (kind stamped, stage file missing)
    # must fall back to the next older models run, not just the newest match
    # (mirrors technique_queries._latest_technique_cards' guarded gateway).
    for rid in reversed(run_store.list_runs()):
        if run_store.read_meta(rid).get("kind") == "models":
            path = run_store._run_dir(rid) / "model_cards.json"
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
    return []


def load_platform_entries(root: Path) -> list[PlatformSeed]:
    """Resolve + load config/platform-matrix.yaml: root override, else the
    packaged seed (same resolution order as the model/technique seeds).

    Single shared path-resolution helper for all three surfaces that read the
    platform matrix (web `/platforms`, this MCP service, `radar export`) —
    mirrors the `load_technique_entries(root)` precedent in
    technique_queries.py. Raises ``PlatformMatrixError`` on a missing/corrupt
    seed; callers choose how to degrade (each surface has its own
    failure-handling convention, so the swallowing stays at the call site,
    not here).
    """
    seed_path = Path(root) / "config" / "platform-matrix.yaml"
    if not seed_path.exists():
        seed_path = Path(__file__).resolve().parents[3] / "config" / "platform-matrix.yaml"
    return load_platform_matrix(seed_path)


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
        profile: str | None = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        entries = self._entries()
        if profile:
            entries = rescore_entries(entries, profile)  # raises ModelProfileError if unknown
        for entry in entries:
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
        mom = compute_model_momentum(model_id, store.history_for(model_id), events, now=datetime.now(UTC))
        data["momentum"] = {"direction": mom.direction,
                            "downloads_growth_pct": mom.downloads_growth_pct}
        data["techniques"] = self._model_techniques(model_id)
        data["benchmark_aggregates"] = self._benchmark_aggregates(model_id)
        return data

    def _benchmark_aggregates(self, model_id: str) -> list[dict[str, Any]]:
        """Triangulated benchmark view for one model; [] on any gap."""
        try:
            from radar.discovery.benchmark_sweep import load_benchmark_sources
            from radar.models_radar.benchmarks import (
                DEFAULT_TRIANGULATION_GAP_POINTS,
                build_benchmark_aggregates,
            )
            from radar.models_radar.seed import load_model_seed
            from radar.storage.benchmark_observations_log import (
                load_benchmark_observations,
            )

            # Aggregate across ALL tracked models so this model's
            # percentiles reflect the real tracked-set ranking.
            observations = load_benchmark_observations(
                self.root / "data" / "benchmark-observations.jsonl"
            )
            seed_path = self.root / "config" / "model-seed.yaml"
            seeds = load_model_seed(seed_path) if seed_path.exists() else []
            sources_path = self.root / "config" / "benchmark-sources.yaml"
            gap_points = (
                load_benchmark_sources(sources_path).triangulation_gap_points
                if sources_path.exists()
                else DEFAULT_TRIANGULATION_GAP_POINTS
            )
            aggregates = build_benchmark_aggregates(
                {seed.id: seed for seed in seeds},
                observations,
                gap_points=gap_points,
            )
            return aggregates.get(model_id, [])
        except Exception:
            return []

    def _model_techniques(self, model_id: str) -> list[dict[str, Any]]:
        """Techniques this model implements (best-effort, [] on any gap)."""
        try:
            from radar.mcp_server.technique_queries import load_technique_entries
            from radar.research_radar.pedigree import build_pedigree_index, pedigree_for_refs

            entries = load_technique_entries(self.root)
            if not entries:
                return []
            items = pedigree_for_refs(build_pedigree_index(entries).by_model_ref, [model_id])
            return [{"id": t.technique_id, "name": t.name,
                     "ring": t.ring.value if t.ring else None,
                     "citation_count": t.citation_count} for t in items]
        except Exception:
            return []

    def list_devices(self) -> list[dict[str, Any]]:
        return [
            {"id": key, "name": d.name, "kind": d.kind,
             "total_memory_gb": d.total_memory_gb, "gpu_count": d.gpu_count,
             "usable_gb": usable_memory_gb(d)}
            for key, d in {**DEVICE_PRESETS, **NODE_PRESETS, **CLUSTER_PRESETS}.items()
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

    def _platform_entries(self) -> list[PlatformSeed]:
        """Load the platform capability matrix; [] on a missing/corrupt seed."""
        try:
            return load_platform_entries(self.root)
        except PlatformMatrixError as exc:
            logger.warning("Platform matrix unreadable under %s: %s", self.root, exc)
            return []

    def get_platform_support(
        self, platform: str | None = None, feature: str | None = None,
    ) -> list[dict[str, Any]]:
        """Filter the platform capability matrix.

        No args: one full row per platform (id/name/hardware/features/
        sources/verified/notes). `platform`: only that engine's row.
        `feature`: one compact row per matching platform —
        {platform, feature, support, sources} — looked up across both the
        hardware and feature key namespaces (they never collide).
        """
        entries = self._platform_entries()
        if platform:
            entries = [e for e in entries if e.id == platform.lower()]
        if feature:
            return [
                {
                    "platform": e.id,
                    "feature": feature,
                    "support": {**e.hardware, **e.features}.get(feature, "unknown"),
                    "sources": e.sources,
                }
                for e in entries
            ]
        return [e.model_dump(mode="json") for e in entries]

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
                entry.id, store.history_for(entry.id), by_model.get(entry.id, []),
                now=datetime.now(UTC))
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
