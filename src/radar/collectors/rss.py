"""RSS and Atom feed collector."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

import feedparser
import httpx
from dateutil import parser as date_parser

from radar.collectors.base import BaseCollector
from radar.models import Signal, SourceConfig


logger = logging.getLogger(__name__)


class RSSCollector(BaseCollector):
    """Collect signals from RSS or Atom feeds."""

    def __init__(self, sources: list[SourceConfig], client: httpx.AsyncClient):
        self.sources = sources
        self.client = client

    async def fetch(self, since: datetime) -> list[Signal]:
        signals: list[Signal] = []
        for source in self.sources:
            if not source.enabled:
                continue
            signals.extend(await self._fetch_source(source, since))
        return signals

    async def _fetch_source(self, source: SourceConfig, since: datetime) -> list[Signal]:
        try:
            response = await self.client.get(str(source.url), follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("RSS source %s failed: %s", source.id, exc)
            return []

        feed = feedparser.parse(response.text)
        signals: list[Signal] = []
        for entry in feed.entries:
            published_at = self._published_at(entry)
            if published_at < since:
                continue
            link = entry.get("link") or str(source.url)
            title = entry.get("title") or source.project
            summary = entry.get("summary") or entry.get("description") or ""
            signals.append(
                Signal(
                    id=f"rss:{source.id}:{self._stable_key(link)}",
                    source_id=source.id,
                    project=source.project,
                    category=source.category,
                    title=title,
                    url=link,
                    published_at=published_at,
                    raw_summary=summary,
                    signal_type="rss_entry",
                    tags=source.tags,
                    metadata={"feed": source.id},
                )
            )
        return signals

    @staticmethod
    def _stable_key(value: str) -> str:
        if value.startswith("http"):
            return value
        return hashlib.sha1(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _published_at(entry) -> datetime:
        raw = entry.get("published") or entry.get("updated") or entry.get("created")
        if raw:
            parsed = date_parser.parse(raw)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        return datetime.now(timezone.utc)
