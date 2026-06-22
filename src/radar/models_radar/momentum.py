"""Model momentum: rising/falling by downloads growth + ring events."""

from __future__ import annotations

from pydantic import BaseModel

from radar.models_radar.history import ModelHistoryEvent
from radar.storage.history_store import ChangeType
from radar.storage.model_metrics_store import ModelMetrics


RISING_PCT = 5.0
FALLING_PCT = -5.0
RECENT_EVENTS = 3


class ModelMomentum(BaseModel):
    model_id: str
    direction: str  # rising | falling | steady
    downloads_growth_pct: float | None = None
    note: str = ""


def _downloads_growth_pct(rows: list[ModelMetrics]) -> float | None:
    points = [r.downloads for r in rows if r.downloads is not None]
    if len(points) < 2 or not points[0]:
        return None
    return round((points[-1] - points[0]) / points[0] * 100, 1)


def compute_model_momentum(
    model_id: str,
    metric_rows: list[ModelMetrics],
    ring_events: list[ModelHistoryEvent],
) -> ModelMomentum:
    """Direction of travel (rows + events oldest-first)."""
    growth = _downloads_growth_pct(metric_rows)
    for event in reversed(ring_events[-RECENT_EVENTS:]):
        if event.change_type == ChangeType.PROMOTED:
            return ModelMomentum(model_id=model_id, direction="rising",
                                 downloads_growth_pct=growth,
                                 note=f"Promoted to {event.ring.value} on {event.observed_at.date()}.")
        if event.change_type == ChangeType.DEMOTED:
            return ModelMomentum(model_id=model_id, direction="falling",
                                 downloads_growth_pct=growth,
                                 note=f"Demoted to {event.ring.value} on {event.observed_at.date()}.")
    if growth is not None:
        if growth >= RISING_PCT:
            return ModelMomentum(model_id=model_id, direction="rising",
                                 downloads_growth_pct=growth,
                                 note=f"Downloads {growth:+.1f}% across recent scans.")
        if growth <= FALLING_PCT:
            return ModelMomentum(model_id=model_id, direction="falling",
                                 downloads_growth_pct=growth,
                                 note=f"Downloads {growth:+.1f}% across recent scans.")
    return ModelMomentum(model_id=model_id, direction="steady", downloads_growth_pct=growth)
