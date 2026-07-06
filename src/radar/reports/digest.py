"""Assemble one ISO-week digest from the committed radar data (pure, no I/O)."""

from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from radar.discovery.trending_entities import Lane, TrendingEntry
from radar.models_radar.history import ModelHistoryEvent
from radar.research_radar.history import TechniqueHistoryEvent
from radar.storage.autopilot_log import AutopilotEntry
from radar.storage.history_log import ProjectHistoryEvent


def iso_week_bounds(now: datetime) -> tuple[datetime, datetime]:
    """[Monday 00:00, next Monday 00:00) of now's ISO week (tz preserved)."""
    monday = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return monday, monday + timedelta(days=7)


def week_label(now: datetime) -> str:
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


class DigestChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str  # tool | model | technique
    name: str
    change_type: str
    ring: str
    previous_ring: str | None
    observed_at: datetime


class WeeklyDigest(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    week_start: datetime
    week_end: datetime
    generated_at: datetime
    trending_onprem: list[TrendingEntry] = Field(default_factory=list)
    trending_broader: list[TrendingEntry] = Field(default_factory=list)
    auto_added: list[AutopilotEntry] = Field(default_factory=list)
    changes: list[DigestChange] = Field(default_factory=list)

    @property
    def summary_line(self) -> str:
        return (f"Week {self.label}: {len(self.auto_added)} source(s) added · "
                f"{len(self.changes)} ring change(s) · "
                f"{len(self.trending_onprem)} on-prem candidate(s)")


def _change(
    kind: str,
    name: str,
    ev: ProjectHistoryEvent | ModelHistoryEvent | TechniqueHistoryEvent,
) -> DigestChange:
    return DigestChange(
        kind=kind, name=name,
        change_type=ev.change_type.value, ring=ev.ring.value,
        previous_ring=ev.previous_ring.value if ev.previous_ring else None,
        observed_at=ev.observed_at,
    )


def build_digest(
    now: datetime,
    trending: list[TrendingEntry],
    autopilot: list[AutopilotEntry],
    tool_events: list[ProjectHistoryEvent],
    model_events: list[ModelHistoryEvent],
    technique_events: list[TechniqueHistoryEvent],
    *,
    top_n: int = 5,
) -> WeeklyDigest:
    start, end = iso_week_bounds(now)

    def _in_week(when: datetime) -> bool:
        return start <= when < end

    onprem = [e for e in trending if e.lane == Lane.ONPREM][:top_n]
    broader = [e for e in trending if e.lane == Lane.BROADER][:top_n]
    auto_added = [a for a in autopilot if _in_week(a.added_at)]

    changes: list[DigestChange] = []
    changes += [_change("tool", e.project, e) for e in tool_events if _in_week(e.observed_at)]
    changes += [_change("model", e.model_id, e) for e in model_events if _in_week(e.observed_at)]
    changes += [_change("technique", e.technique_id, e)
                for e in technique_events if _in_week(e.observed_at)]
    changes.sort(key=lambda c: c.observed_at, reverse=True)

    return WeeklyDigest(
        label=week_label(now), week_start=start, week_end=end, generated_at=now,
        trending_onprem=onprem, trending_broader=broader,
        auto_added=auto_added, changes=changes,
    )
