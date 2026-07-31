"""RSS and Atom release discovery with provenance classification."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import feedparser
import httpx
from pydantic import Field

from radar.intelligence.contracts import EvidenceStrength, FrozenModel
from radar.intelligence.sources.base import DiscoveryCandidate, SourceRecord
from radar.intelligence.sources.utils import (
    canonical_url,
    parse_datetime,
    url_is_official,
)


class FeedConfig(FrozenModel):
    id: str
    url: str
    publisher_id: str
    official_domains: list[str] = Field(default_factory=list)
    enabled: bool = True


class OfficialFeedAdapter:
    id = "official-feeds"

    def __init__(
        self,
        client: httpx.AsyncClient,
        feeds: list[FeedConfig],
        *,
        source_id: str = "official-feeds",
        clock: Callable[[], datetime] | None = None,
    ):
        self.client = client
        self.feeds = feeds
        self.id = source_id
        self.clock = clock or (lambda: datetime.now(UTC))
        self.warnings: list[str] = []

    async def discover(self, since: datetime) -> list[DiscoveryCandidate]:
        candidates: list[DiscoveryCandidate] = []
        for feed in sorted(self.feeds, key=lambda item: item.id):
            if not feed.enabled:
                continue
            strength = (
                EvidenceStrength.OFFICIAL_ANNOUNCEMENT
                if url_is_official(feed.url, feed.official_domains)
                else EvidenceStrength.AGGREGATOR
            )
            response = await self.client.get(feed.url)
            response.raise_for_status()
            record = SourceRecord.from_bytes(
                source_id=self.id,
                url=str(response.request.url),
                body=response.content,
                retrieved_at=self.clock(),
                strength=strength,
                content_type=response.headers.get("content-type"),
            )
            parsed = feedparser.parse(response.content)
            if parsed.bozo:
                self.warnings.append(
                    f"{feed.id}: feed parse warning: "
                    f"{getattr(parsed, 'bozo_exception', 'unknown')}"
                )
            for entry in parsed.entries:
                published_at = _entry_datetime(entry)
                if published_at is None or published_at < since:
                    continue
                link = canonical_url(str(entry.get("link") or feed.url))
                external_id = str(
                    entry.get("id")
                    or entry.get("guid")
                    or _stable_entry_id(feed.id, entry, link)
                )
                title = str(entry.get("title") or external_id)
                candidates.append(
                    DiscoveryCandidate(
                        source_record=record,
                        external_id=external_id,
                        publisher_hint=feed.publisher_id,
                        release_name=title,
                        artifact_urls=[link],
                        claims={
                            "published_at": published_at.isoformat(),
                            "summary": str(
                                entry.get("summary")
                                or entry.get("description")
                                or ""
                            ),
                        },
                    )
                )
        return sorted(
            candidates,
            key=lambda candidate: candidate.external_id.casefold(),
        )

    async def fetch(self, url: str) -> SourceRecord:
        response = await self.client.get(url)
        response.raise_for_status()
        return SourceRecord.from_bytes(
            source_id=self.id,
            url=str(response.request.url),
            body=response.content,
            retrieved_at=self.clock(),
            strength=EvidenceStrength.AGGREGATOR,
            content_type=response.headers.get("content-type"),
        )


def _entry_datetime(entry: Any) -> datetime | None:
    return parse_datetime(
        entry.get("published")
        or entry.get("updated")
        or entry.get("created")
    )


def _stable_entry_id(feed_id: str, entry: Any, link: str) -> str:
    import hashlib
    import json

    body = json.dumps(
        {
            "feed": feed_id,
            "title": entry.get("title"),
            "link": link,
            "published": entry.get("published") or entry.get("updated"),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"feed:{feed_id}:{hashlib.sha256(body).hexdigest()}"
