"""Conditional discovery from stable official announcement pages."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx
from pydantic import Field

from radar.intelligence.contracts import EvidenceStrength, FrozenModel
from radar.intelligence.sources.base import DiscoveryCandidate, SourceRecord
from radar.intelligence.sources.utils import (
    canonical_url,
    parse_datetime,
    url_is_official,
)


class AnnouncementConfig(FrozenModel):
    id: str
    url: str
    publisher_id: str
    official_domains: list[str] = Field(default_factory=list)
    enabled: bool = True
    selectors: list[str] = Field(default_factory=lambda: ["a"])


@dataclass
class _Cursor:
    etag: str | None = None
    last_modified: str | None = None
    checksum: str | None = None


class _LinkParser(HTMLParser):
    def __init__(self, selectors: list[str]) -> None:
        super().__init__()
        self.selectors = selectors
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        if tag.casefold() == "a" and any(
            _selector_matches(tag, attributes, selector)
            for selector in self.selectors
        ):
            self._href = attributes.get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self._href:
            text = " ".join("".join(self._text).split())
            self.links.append((self._href, text or self._href))
            self._href = None
            self._text = []


class AnnouncementPageAdapter:
    id = "announcements"

    def __init__(
        self,
        client: httpx.AsyncClient,
        pages: list[AnnouncementConfig],
        *,
        source_id: str = "announcements",
        clock: Callable[[], datetime] | None = None,
    ):
        self.client = client
        self.pages = pages
        self.id = source_id
        self.clock = clock or (lambda: datetime.now(UTC))
        self.cursors: dict[str, _Cursor] = {}
        self.warnings: list[str] = []

    async def discover(self, since: datetime) -> list[DiscoveryCandidate]:
        candidates: list[DiscoveryCandidate] = []
        for page in sorted(self.pages, key=lambda item: item.id):
            if not page.enabled:
                continue
            cursor = self.cursors.setdefault(page.id, _Cursor())
            headers = {}
            if cursor.etag:
                headers["If-None-Match"] = cursor.etag
            if cursor.last_modified:
                headers["If-Modified-Since"] = cursor.last_modified
            response = await self.client.get(page.url, headers=headers)
            if response.status_code == 304:
                continue
            response.raise_for_status()
            strength = (
                EvidenceStrength.OFFICIAL_ANNOUNCEMENT
                if url_is_official(page.url, page.official_domains)
                else EvidenceStrength.AGGREGATOR
            )
            record = SourceRecord.from_bytes(
                source_id=self.id,
                url=str(response.request.url),
                body=response.content,
                retrieved_at=self.clock(),
                strength=strength,
                content_type=response.headers.get("content-type"),
            )
            if cursor.checksum == record.checksum:
                continue
            cursor.etag = response.headers.get("etag")
            cursor.last_modified = response.headers.get("last-modified")
            cursor.checksum = record.checksum
            modified_at = parse_datetime(cursor.last_modified) or self.clock()
            if modified_at < since:
                continue
            parser = _LinkParser(page.selectors)
            parser.feed(response.text)
            if not parser.links:
                self.warnings.append(
                    f"{page.id}: selectors {page.selectors!r} matched no links"
                )
            for href, title in parser.links:
                link = canonical_url(urljoin(page.url, href))
                candidates.append(
                    DiscoveryCandidate(
                        source_record=record,
                        external_id=link,
                        publisher_hint=page.publisher_id,
                        release_name=title,
                        artifact_urls=[link],
                        claims={"page_modified_at": modified_at.isoformat()},
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


def _selector_matches(
    tag: str,
    attributes: dict[str, str | None],
    selector: str,
) -> bool:
    selector = selector.strip()
    if not selector:
        return False
    selector_tag = ""
    selector_id = ""
    selector_class = ""
    if "#" in selector:
        selector_tag, selector_id = selector.split("#", 1)
    elif "." in selector:
        selector_tag, selector_class = selector.split(".", 1)
    else:
        selector_tag = selector
    if selector_tag and selector_tag.casefold() != tag.casefold():
        return False
    if selector_id and attributes.get("id") != selector_id:
        return False
    classes = (attributes.get("class") or "").split()
    return not selector_class or selector_class in classes
