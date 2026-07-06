"""Entities for the trending radar: lane, observation rows, derived entries."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Lane(str, Enum):
    """Which net caught a repo. onprem = strict radar identity (can promote);
    broader = general AI heat (content only, never promotes)."""

    ONPREM = "onprem"
    BROADER = "broader"


class TrendingObservation(BaseModel):
    """One repo's state on one sweep day. Velocity is derived from many of these."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str  # "owner/name"
    lane: Lane
    stars: int
    observed_at: datetime
    repo_created_at: datetime
    description: str = ""
    topics: list[str] = Field(default_factory=list)
    license: str | None = None  # spdx_id from the search payload; None/"NOASSERTION" = unknown

    @field_validator("observed_at")
    @classmethod
    def _ensure_aware(cls, v: datetime) -> datetime:
        # A hand-edited/merge-mangled line can drop the UTC offset. Normalize
        # here at the model boundary so every consumer's sorted()/comparison
        # sees tz-aware datetimes — never a naive-vs-aware TypeError downstream
        # (momentum_stats, build_trending, etc.).
        return v.replace(tzinfo=UTC) if v.tzinfo is None else v


class TrendingEntry(BaseModel):
    """A repo as seen across its observations (current state + derived growth)."""

    model_config = ConfigDict(frozen=True)

    repo: str
    lane: Lane
    stars: int
    velocity_per_day: float | None
    is_new: bool
    first_seen: str  # ISO date
    description: str = ""
    topics: list[str] = Field(default_factory=list)
    license: str | None = None
