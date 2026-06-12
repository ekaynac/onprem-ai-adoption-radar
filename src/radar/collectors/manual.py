"""Collector for manually configured references."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.collectors.base import BaseCollector
from radar.models import Signal, SourceConfig


class ManualCollector(BaseCollector):
    """Emit one stable signal per manual source."""

    def __init__(self, sources: list[SourceConfig]):
        self.sources = sources

    async def fetch(self, since: datetime) -> list[Signal]:
        """Return configured manual references."""
        now = datetime.now(UTC)
        return [
            Signal(
                id=f"manual:{source.id}",
                source_id=source.id,
                project=source.project,
                category=source.category,
                title=f"{source.project} reference",
                url=source.url,
                published_at=now,
                raw_summary=f"Manual reference for {source.project}",
                signal_type="manual_reference",
                tags=source.tags,
            )
            for source in self.sources
            if source.enabled
        ]
