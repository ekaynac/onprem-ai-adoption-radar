"""Per-project momentum from accumulated metrics and ring history.

Deterministic and explainable: a recent ring move dominates; otherwise the
star trend across the recorded metrics rows decides; otherwise steady.
"""

from __future__ import annotations

from pydantic import BaseModel

from radar.pipeline.delta import ChangeType
from radar.storage.history_store import ProjectHistoryEvent
from radar.storage.metrics_store import ProjectMetrics


# A ring move counts as "recent" while it is within this many most-recent
# history events for the project; after that the star trend takes over.
RECENT_EVENTS = 3
RISING_GROWTH_PCT = 2.0
FALLING_GROWTH_PCT = -1.0


class Momentum(BaseModel):
    """A project's direction of travel."""

    project: str
    direction: str  # rising | falling | steady
    star_growth_pct: float | None = None
    note: str = ""


def compute_momentum(
    project: str,
    metric_rows: list[ProjectMetrics],
    ring_events: list[ProjectHistoryEvent],
) -> Momentum:
    """Direction of travel for one project (rows and events oldest-first)."""
    growth_pct = _star_growth_pct(metric_rows)

    for event in reversed(ring_events[-RECENT_EVENTS:]):
        if event.change_type == ChangeType.PROMOTED:
            return Momentum(
                project=project,
                direction="rising",
                star_growth_pct=growth_pct,
                note=f"Promoted to {event.ring.value} on {event.observed_at.date()}.",
            )
        if event.change_type == ChangeType.DEMOTED:
            return Momentum(
                project=project,
                direction="falling",
                star_growth_pct=growth_pct,
                note=f"Demoted to {event.ring.value} on {event.observed_at.date()}.",
            )

    if growth_pct is not None:
        if growth_pct >= RISING_GROWTH_PCT:
            return Momentum(
                project=project,
                direction="rising",
                star_growth_pct=growth_pct,
                note=f"Stars {growth_pct:+.1f}% across recent scans.",
            )
        if growth_pct <= FALLING_GROWTH_PCT:
            return Momentum(
                project=project,
                direction="falling",
                star_growth_pct=growth_pct,
                note=f"Stars {growth_pct:+.1f}% across recent scans.",
            )

    return Momentum(project=project, direction="steady", star_growth_pct=growth_pct)


def trend_arrow(direction: str) -> str:
    """Compact arrow for tables and cards."""
    return {"rising": "↑", "falling": "↓"}.get(direction, "→")


def _star_growth_pct(rows: list[ProjectMetrics]) -> float | None:
    starred = [row.stars for row in rows if row.stars is not None]
    if len(starred) < 2 or starred[0] == 0:
        return None
    return round((starred[-1] - starred[0]) / starred[0] * 100, 1)
