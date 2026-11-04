"""News: lab and practitioner RSS/Atom feeds plus Hacker News (Algolia).

Item keys are ``news:<sha256(url)[:16]>``, the id the radar has always used,
so the classifier labels already cached stay valid.
"""

from __future__ import annotations

import calendar
import hashlib
import logging
import re
from datetime import UTC, datetime
from typing import Any, Literal

import feedparser
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from radar.pulse.http import get_with_retry
from radar.pulse.items import Lane, PulseItem
from radar.pulse.sources import SourceRun, error_text
from radar.pulse.text import shorten


logger = logging.getLogger(__name__)

# Feeds behind bot protection serve a challenge page to obvious bots; a
# browser-like UA that still names the project honestly gets the real feed.
USER_AGENT = (
    "Mozilla/5.0 (compatible; onprem-ai-adoption-radar/1.0; +https://www.megabilgisayar.com.tr)"
)
ACCEPT = "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"
_TAG = re.compile(r"<[^>]+>")


class NewsSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    kind: Literal["rss", "hn-algolia"]
    url: str = Field(pattern=r"^https?://")
    enabled: bool = True


def news_key(url: str) -> str:
    return "news:" + hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:16]


def _item(source: NewsSource, title: Any, url: Any, summary: Any,
          published: datetime | None, now: datetime) -> PulseItem | None:
    if not isinstance(title, str) or not title.strip() or not isinstance(url, str) or not url:
        return None
    cleaned = _TAG.sub(" ", summary) if isinstance(summary, str) else None
    try:
        return PulseItem(
            lane=Lane.NEWS, key=news_key(url), title=" ".join(title.split()), url=url,
            source=source.id, published_at=published, first_seen=now, last_seen=now,
            summary=shorten(cleaned), kind=source.id,
        )
    except ValidationError as exc:
        logger.warning("Dropping malformed news entry from %s: %s", source.id, exc)
        return None


def parse_rss(text: str, source: NewsSource, now: datetime) -> list[PulseItem]:
    items = []
    for entry in feedparser.parse(text).entries:
        # Undated entries are skipped: with no date they would leave the window
        # by first_seen and come back as "new" every window_days.
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        try:
            published = datetime.fromtimestamp(calendar.timegm(stamp), tz=UTC)
        except (TypeError, ValueError, OverflowError):
            continue
        item = _item(source, entry.get("title"), entry.get("link"), entry.get("summary"),
                     published, now)
        if item is not None:
            items.append(item)
    return items


def parse_hn(payload: Any, source: NewsSource, now: datetime) -> list[PulseItem]:
    hits = payload.get("hits") if isinstance(payload, dict) else None
    if not isinstance(hits, list):
        raise ValueError(f"{source.id}: expected a 'hits' list")
    items = []
    for hit in hits:
        if not isinstance(hit, dict) or not hit.get("objectID"):
            continue
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}"
        published = None
        if isinstance(hit.get("created_at"), str):
            try:
                published = datetime.fromisoformat(hit["created_at"].replace("Z", "+00:00"))
            except ValueError:
                published = None
        item = _item(source, hit.get("title"), url, None, published, now)
        if item is not None:
            items.append(item)
    return items


async def fetch_news(client: Any, sources: list[NewsSource], now: datetime) -> SourceRun:
    enabled = [s for s in sources if s.enabled]
    items: dict[str, PulseItem] = {}
    errors: list[str] = []
    for source in enabled:
        try:
            response = await get_with_retry(
                client, source.url, label=f"news:{source.id}",
                headers={"User-Agent": USER_AGENT, "Accept": ACCEPT}, follow_redirects=True,
            )
            parsed = (parse_rss(response.text, source, now) if source.kind == "rss"
                      else parse_hn(response.json(), source, now))
        except Exception as exc:
            errors.append(f"{source.id}: {error_text(exc)}")
            continue
        for item in parsed:
            items.setdefault(item.key, item)
    return SourceRun("news:feeds", tuple(items.values()), len(enabled), tuple(errors))
