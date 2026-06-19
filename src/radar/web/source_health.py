"""Summarize per-source signal health into a small display view.

The orchestrator records how many raw signals each source produced per scan
(``SourceHealthStore``). A source silent for a full stale window is probably
broken rather than merely quiet. This pure helper turns the store's stale set +
latest counts into an immutable, display-ready summary for the dashboard and the
static export — mirroring ``scan_health.summarize_meta``. Defensive by design:
inputs are never mutated and missing data degrades to an empty, healthy view.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field

from radar.models import SourceConfig


class StaleFeed(BaseModel):
    """One source flagged as stale, with its display context."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    project: str
    last_count: int = 0
    firehose: bool = False


class SourceHealth(BaseModel):
    """Immutable, display-ready summary of source/feed health."""

    model_config = ConfigDict(frozen=True)

    total_sources: int = 0
    stale: list[StaleFeed] = Field(default_factory=list)

    @property
    def has_stale(self) -> bool:
        return bool(self.stale)

    @property
    def one_line(self) -> str:
        """Compact human summary for the template header."""
        if not self.total_sources:
            return "Source health: no scans yet."
        if not self.stale:
            return f"Source health: all {self.total_sources} feeds active."
        noun = "feed" if len(self.stale) == 1 else "feeds"
        return f"Source health: {len(self.stale)} stale {noun} of {self.total_sources}."


def summarize_source_health(
    stale_ids: Iterable[str],
    latest_counts: Mapping[str, int],
    sources: Iterable[SourceConfig],
) -> SourceHealth:
    """Build a SourceHealth from the store's stale set + latest counts.

    Only enabled sources count toward ``total_sources``; a stale id without a
    matching configured source is skipped (config may have changed since the
    scan that recorded it).
    """
    enabled = [s for s in sources if s.enabled]
    stale_set = set(stale_ids)
    by_id = {s.id: s for s in enabled}
    stale = [
        StaleFeed(
            source_id=source.id,
            project=source.project,
            last_count=int(latest_counts.get(source.id, 0)),
            firehose=bool(source.firehose),
        )
        for sid in sorted(stale_set)
        if (source := by_id.get(sid)) is not None
    ]
    return SourceHealth(total_sources=len(enabled), stale=stale)
