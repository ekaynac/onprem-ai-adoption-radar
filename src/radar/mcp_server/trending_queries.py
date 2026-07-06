"""Query service over the trending observation store (mirror of the model/technique services)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from radar.discovery.trending_detect import build_trending
from radar.discovery.trending_entities import TrendingEntry
from radar.storage.trending_observations_log import load_observations


logger = logging.getLogger(__name__)


def load_trending_entries(root: Path, now: datetime) -> list[TrendingEntry]:
    """Derived trending entries from the observation store; [] on ANY failure.

    Guarded gateway: a corrupt or absent store degrades to "no trending data"
    on every surface rather than raising.
    """
    try:
        path = Path(root) / "data" / "trending-observations.jsonl"
        return build_trending(load_observations(path), now)
    except Exception as exc:
        logger.warning("Trending store unreadable under %s: %s", root, exc)
        return []


class TrendingQueryService:
    """Read-only trending queries for the MCP tool (and web/static loaders)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def list_trending(
        self,
        lane: str | None = None,
        limit: int = 20,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        entries = load_trending_entries(self.root, now or datetime.now(UTC))
        if lane:
            entries = [e for e in entries if e.lane.value == lane.lower()]
        return [self._row(e) for e in entries[:max(0, limit)]]

    @staticmethod
    def _row(entry: TrendingEntry) -> dict[str, Any]:
        return {
            "repo": entry.repo,
            "lane": entry.lane.value,
            "stars": entry.stars,
            "velocity_per_day": entry.velocity_per_day,
            "is_new": entry.is_new,
            "first_seen": entry.first_seen,
            "description": entry.description,
            "topics": entry.topics,
        }
