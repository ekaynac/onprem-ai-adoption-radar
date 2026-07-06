"""Trending-hub sections for models & techniques (rising ∪ new-this-week).

Pure builders (``now`` is a parameter) plus one guarded loader that reads the
committed stores. A corrupt/absent store degrades to an empty section — never a
raise — so ``/trending`` and the daily export can never break on hub data.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from radar.models_radar.entities import ModelEntry
from radar.models_radar.history import ModelHistoryEvent
from radar.models_radar.momentum import compute_model_momentum
from radar.reports.digest import iso_week_bounds
from radar.research_radar.entities import TechniqueEntry
from radar.research_radar.history import TechniqueHistoryEvent
from radar.storage.model_metrics_store import ModelMetrics


logger = logging.getLogger(__name__)

RISING_MOMENTUM = 4
_NEW_CHANGES = {"new", "promoted"}


class HubRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    subtitle: str
    metric: int | None
    growth: float | None
    momentum: int | None
    direction: str
    ring: str | None
    is_new: bool
    kind: str  # "model" | "technique" — template builds the per-surface link


def _new_ids(events: list, now: datetime, id_attr: str) -> set[str]:
    start, end = iso_week_bounds(now)
    return {
        getattr(ev, id_attr) for ev in events
        if ev.change_type.value in _NEW_CHANGES and start <= ev.observed_at < end
    }


def build_model_section(
    entries: list[ModelEntry],
    model_metrics: list[ModelMetrics],
    model_events: list[ModelHistoryEvent],
    now: datetime,
    *,
    top_n: int = 10,
) -> list[HubRow]:
    metrics_by_id: dict[str, list[ModelMetrics]] = {}
    for m in model_metrics:
        metrics_by_id.setdefault(m.model_id, []).append(m)
    events_by_id: dict[str, list[ModelHistoryEvent]] = {}
    for ev in model_events:
        events_by_id.setdefault(ev.model_id, []).append(ev)
    new_ids = _new_ids(model_events, now, "model_id")

    def _row(entry: ModelEntry, mom, is_new: bool) -> HubRow:
        return HubRow(
            id=entry.id, name=entry.name, subtitle=entry.family,
            metric=entry.hf_downloads, growth=mom.downloads_growth_pct, momentum=None,
            direction=mom.direction, ring=entry.ring.value if entry.ring else None,
            is_new=is_new, kind="model",
        )

    scored = [
        (e, compute_model_momentum(e.id, metrics_by_id.get(e.id, []), events_by_id.get(e.id, [])))
        for e in entries
    ]
    rising = sorted(
        (em for em in scored if em[1].direction == "rising"),
        key=lambda em: -(em[1].downloads_growth_pct or 0.0),
    )[:top_n]
    rows = [_row(e, m, e.id in new_ids) for e, m in rising]
    seen = {e.id for e, _ in rising}
    rows += [_row(e, m, True) for e, m in scored if e.id in new_ids and e.id not in seen]
    return rows


def build_technique_section(
    entries: list[TechniqueEntry],
    technique_events: list[TechniqueHistoryEvent],
    now: datetime,
    *,
    top_n: int = 10,
) -> list[HubRow]:
    new_ids = _new_ids(technique_events, now, "technique_id")

    def _momentum(e: TechniqueEntry) -> int:
        return e.score_breakdown.momentum if e.score_breakdown else 0

    def _row(entry: TechniqueEntry, is_new: bool) -> HubRow:
        mom = _momentum(entry)
        direction = "rising" if mom >= RISING_MOMENTUM else "falling" if mom <= 2 else "steady"
        return HubRow(
            id=entry.id, name=entry.name, subtitle=entry.domain.value,
            metric=entry.citation_count, growth=None, momentum=mom, direction=direction,
            ring=entry.ring.value if entry.ring else None, is_new=is_new,
            kind="technique",
        )

    rising = sorted(
        (e for e in entries if _momentum(e) >= RISING_MOMENTUM),
        key=lambda e: (-_momentum(e), -(e.citation_count or 0), e.name),
    )[:top_n]
    rows = [_row(e, e.id in new_ids) for e in rising]
    seen = {e.id for e in rising}
    rows += [_row(e, True) for e in entries if e.id in new_ids and e.id not in seen]
    return rows


def load_hub_sections(root: Path, now: datetime) -> tuple[list[HubRow], list[HubRow]]:
    """Guarded gateway: build both sections from committed stores; ([], []) on any failure."""
    from radar.mcp_server.model_queries import _latest_model_cards
    from radar.mcp_server.technique_queries import load_technique_entries
    from radar.models_radar.history import load_model_events
    from radar.research_radar.history import load_technique_events
    from radar.storage.model_metrics_log import load_model_metrics

    try:
        root = Path(root)
        model_entries = [ModelEntry.model_validate(c) for c in _latest_model_cards(root)]
        model_rows = build_model_section(
            model_entries,
            load_model_metrics(root / "data" / "model-metrics.jsonl"),
            load_model_events(root / "data" / "model-history.jsonl"),
            now,
        )
        technique_rows = build_technique_section(
            load_technique_entries(root),
            load_technique_events(root / "data" / "technique-history.jsonl"),
            now,
        )
        return model_rows, technique_rows
    except Exception as exc:
        logger.warning("Trending-hub sections unavailable under %s: %s", root, exc)
        return [], []
