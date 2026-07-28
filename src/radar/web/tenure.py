"""Tenure credential: how long a project/model has been on the radar.

The differentiation-pass answer to trendshift's "Featured N times" archive —
except computed from the EFFECTIVE (outage-corrected) timeline, so the
credential can't be inflated by instrument noise (spec 2026-07-28 §F1).
"""

from __future__ import annotations

from datetime import datetime
from itertools import pairwise

from pydantic import BaseModel, ConfigDict

from radar.models_radar.history import ModelHistoryEvent
from radar.storage.history_store import ProjectHistoryEvent, apply_corrections


class TenureLine(BaseModel):
    """One rendered credential line for a card or detail page."""

    model_config = ConfigDict(frozen=True)

    days_on_radar: int
    ring: str
    ring_since: str  # ISO date the current unbroken ring streak started
    change_count: int

    @property
    def text(self) -> str:
        prefix = (
            "On radar since today"
            if self.days_on_radar == 0
            else f"On radar {self.days_on_radar} days"
        )
        plural = "" if self.change_count == 1 else "s"
        return (
            f"{prefix} · {self.ring.upper()} since {self.ring_since} · "
            f"{self.change_count} ring change{plural}"
        )


def project_tenure(
    events: list[ProjectHistoryEvent], now: datetime
) -> TenureLine | None:
    """Tenure over the effective timeline; None when nothing effective remains."""
    effective = apply_corrections(events)
    return _tenure([(e.observed_at, e.ring.value) for e in effective], now)


def model_tenure(events: list[ModelHistoryEvent], now: datetime) -> TenureLine | None:
    """Tenure over the raw model timeline (no correction concept for models)."""
    return _tenure([(e.observed_at, e.ring.value) for e in events], now)


def _tenure(points: list[tuple[datetime, str]], now: datetime) -> TenureLine | None:
    """Shared math: points are (observed_at, ring_value), any order in.

    `change_count` counts ring TRANSITIONS only — an `updated` event at the
    same ring is not a change. This deliberately differs from
    `ProjectHistorySummary.change_count`, which counts events.
    """
    if not points:
        return None
    points = sorted(points, key=lambda p: p[0])
    ring = points[-1][1]
    streak_start = points[-1][0]
    for observed_at, ring_value in reversed(points):
        if ring_value != ring:
            break
        streak_start = observed_at
    rings = [p[1] for p in points]
    transitions = sum(1 for prev, cur in pairwise(rings) if cur != prev)
    return TenureLine(
        days_on_radar=(now.date() - points[0][0].date()).days,
        ring=ring,
        ring_since=streak_start.date().isoformat(),
        change_count=transitions,
    )
