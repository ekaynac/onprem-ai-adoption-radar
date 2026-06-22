"""Model decision pipeline: score → diff rings → persist metrics + history."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from radar.models import Ring
from radar.models_radar.entities import ModelEntry
from radar.models_radar.history import (
    ModelHistoryEvent,
    append_model_events,
    diff_model_rings,
    load_model_events,
)
from radar.models_radar.memory import minimum_viable_quant
from radar.models_radar.momentum import ModelMomentum, compute_model_momentum
from radar.models_radar.scoring import model_ring, score_model
from radar.storage.model_metrics_store import ModelMetrics, ModelMetricsStore


def score_entries(entries: list[ModelEntry]) -> list[ModelEntry]:
    """Return new entries with score/score_breakdown/ring populated."""
    scored: list[ModelEntry] = []
    for entry in entries:
        breakdown = score_model(entry)
        ring = model_ring(breakdown)
        scored.append(entry.model_copy(update={
            "score": breakdown.average, "score_breakdown": breakdown, "ring": ring,
        }))
    return scored


def _latest_rings(history_path: Path) -> dict[str, Ring]:
    """Most recent ring per model from the durable log."""
    rings: dict[str, Ring] = {}
    for event in load_model_events(history_path):  # oldest-first → last wins
        rings[event.model_id] = event.ring
    return rings


def persist_model_scan(
    entries: list[ModelEntry],
    run_id: str,
    observed_at: datetime,
    db_path: Path,
    history_path: Path,
) -> list[ModelHistoryEvent]:
    """Diff rings vs the log, append new events, record per-scan metrics."""
    previous = _latest_rings(history_path)
    events = diff_model_rings(entries, previous, run_id, observed_at)
    append_model_events(history_path, events)

    store = ModelMetricsStore(db_path)
    store.initialize()
    rows: list[ModelMetrics] = []
    for entry in entries:
        mv = minimum_viable_quant(entry.quants)
        rows.append(ModelMetrics(
            model_id=entry.id, run_id=run_id, observed_at=observed_at,
            downloads=entry.hf_downloads, likes=entry.hf_likes,
            min_memory_gb=(mv.est_memory_gb_4k if mv else None),
            ring=(entry.ring.value if entry.ring else None),
            hardware_tier=entry.hardware_tier.value,
        ))
    store.record(rows)
    return events


def momentum_for(
    entries: list[ModelEntry], db_path: Path, history_path: Path,
) -> dict[str, ModelMomentum]:
    """Momentum per model from its metric history + ring events."""
    store = ModelMetricsStore(db_path)
    store.initialize()
    events = load_model_events(history_path)
    events_by_model: dict[str, list[ModelHistoryEvent]] = {}
    for ev in events:
        events_by_model.setdefault(ev.model_id, []).append(ev)
    result: dict[str, ModelMomentum] = {}
    for entry in entries:
        result[entry.id] = compute_model_momentum(
            entry.id, store.history_for(entry.id), events_by_model.get(entry.id, []),
        )
    return result
