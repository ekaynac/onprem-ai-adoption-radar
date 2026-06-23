"""Per-project momentum from accumulated metrics and ring history.

Deterministic and explainable. Signals are weighed in priority order: a recent
ring move dominates; then the star trend; then the weekly-download trend; then a
rise in research/community interest (arXiv + Hacker News mentions). The first
signal that crosses a threshold sets the direction and explains itself in the
note. Otherwise: steady.
"""

from __future__ import annotations

from pydantic import BaseModel

from radar.pipeline.delta import ChangeType
from radar.storage.history_store import ProjectHistoryEvent
from radar.storage.metrics_store import ProjectMetrics


# A ring move counts as "recent" while it is within this many most-recent
# history events for the project; after that the metric trends take over.
RECENT_EVENTS = 3
RISING_GROWTH_PCT = 2.0
FALLING_GROWTH_PCT = -1.0
# Mention counts are small integers where percentages are noisy (0 → 3 is not
# "infinite growth"); an absolute increase across the window flags rising interest.
MENTION_RISE_ABS = 2


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
    star_pct = _growth_pct([row.stars for row in metric_rows])
    downloads_pct = _growth_pct([row.downloads_weekly for row in metric_rows])
    paper_rise = _count_increase([row.paper_mentions for row in metric_rows])
    hn_rise = _count_increase([row.hn_mentions for row in metric_rows])

    def momentum(direction: str, note: str) -> Momentum:
        return Momentum(project=project, direction=direction, star_growth_pct=star_pct, note=note)

    # 1. A recent ring move dominates.
    for event in reversed(ring_events[-RECENT_EVENTS:]):
        if event.change_type == ChangeType.PROMOTED:
            return momentum("rising", f"Promoted to {event.ring.value} on {event.observed_at.date()}.")
        if event.change_type == ChangeType.DEMOTED:
            return momentum("falling", f"Demoted to {event.ring.value} on {event.observed_at.date()}.")

    # 2. Star trend (primary growth signal).
    if star_pct is not None:
        if star_pct >= RISING_GROWTH_PCT:
            return momentum("rising", f"Stars {star_pct:+.1f}% across recent scans.")
        if star_pct <= FALLING_GROWTH_PCT:
            return momentum("falling", f"Stars {star_pct:+.1f}% across recent scans.")

    # 3. Weekly-download trend (secondary percentage signal).
    if downloads_pct is not None:
        if downloads_pct >= RISING_GROWTH_PCT:
            return momentum("rising", f"Downloads {downloads_pct:+.1f}% across recent scans.")
        if downloads_pct <= FALLING_GROWTH_PCT:
            return momentum("falling", f"Downloads {downloads_pct:+.1f}% across recent scans.")

    # 4. Research / community interest (count-based, rising-only).
    if paper_rise >= MENTION_RISE_ABS:
        return momentum("rising", f"Paper mentions +{paper_rise} across recent scans.")
    if hn_rise >= MENTION_RISE_ABS:
        return momentum("rising", f"HN mentions +{hn_rise} across recent scans.")

    return momentum("steady", "")


def trend_arrow(direction: str) -> str:
    """Compact arrow for tables and cards."""
    return {"rising": "↑", "falling": "↓"}.get(direction, "→")


def _growth_pct(values: list[int | None]) -> float | None:
    """Percent change first→last across present values (None if <2 or first is 0)."""
    present = [v for v in values if v is not None]
    if len(present) < 2 or present[0] == 0:
        return None
    return round((present[-1] - present[0]) / present[0] * 100, 1)


def _count_increase(values: list[int | None]) -> int:
    """Absolute first→last increase across present values (0 if fewer than two)."""
    present = [v for v in values if v is not None]
    if len(present) < 2:
        return 0
    return present[-1] - present[0]
