"""Sweep RSS/Atom feeds and HN Algolia into raw news items (config-driven).

One adapter per source kind; a failing source degrades to an ``error``
outcome without aborting the others (same contract as the benchmark and
trending sweeps). Items carry a stable URL-derived id so the store can
dedupe at write time — articles are static, not time series.
"""

from __future__ import annotations

import calendar
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import feedparser
import yaml
from pydantic import BaseModel, ConfigDict

from radar.storage.news_log import NewsItem, news_id_for


logger = logging.getLogger(__name__)

_SUMMARY_MAX_CHARS = 500
_TAG_RE = re.compile(r"<[^>]+>")


class NewsClassificationConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool
    model: str
    max_items_per_run: int
    max_output_tokens: int


class NewsSourceConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    kind: Literal["rss", "hn-algolia"]
    enabled: bool
    url: str


class NewsSourcesConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    classification: NewsClassificationConfig
    sources: list[NewsSourceConfig]


def load_news_sources(path: Path) -> NewsSourcesConfig:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return NewsSourcesConfig.model_validate(payload)


@dataclass
class NewsSweepResult:
    items: list[NewsItem] = field(default_factory=list)
    outcomes: dict[str, dict[str, Any]] = field(default_factory=dict)


def _clean_summary(raw: Any) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = _TAG_RE.sub(" ", raw)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_SUMMARY_MAX_CHARS] or None


def _struct_to_datetime(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(calendar.timegm(value), tz=UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def _parse_rss(
    text: str, source: NewsSourceConfig, now: datetime
) -> list[NewsItem]:
    parsed = feedparser.parse(text)
    items: list[NewsItem] = []
    for entry in parsed.entries:
        url = entry.get("link")
        title = entry.get("title")
        if not url or not title:
            continue
        published = entry.get("published_parsed") or entry.get(
            "updated_parsed"
        )
        items.append(
            NewsItem(
                id=news_id_for(url),
                source_id=source.id,
                title=str(title).strip(),
                url=str(url),
                summary=_clean_summary(entry.get("summary")),
                published_at=(
                    _struct_to_datetime(published) if published else None
                ),
                observed_at=now,
            )
        )
    return items


def _parse_hn(
    payload: Any, source: NewsSourceConfig, now: datetime
) -> list[NewsItem]:
    hits = payload.get("hits") if isinstance(payload, dict) else None
    if not isinstance(hits, list):
        raise ValueError(f"{source.id}: expected a 'hits' list")
    items: list[NewsItem] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        title = hit.get("title")
        object_id = hit.get("objectID")
        if not title or not object_id:
            continue
        url = hit.get("url") or (
            f"https://news.ycombinator.com/item?id={object_id}"
        )
        published: datetime | None = None
        created_at = hit.get("created_at")
        if isinstance(created_at, str):
            try:
                published = datetime.fromisoformat(
                    created_at.replace("Z", "+00:00")
                )
            except ValueError:
                published = None
        items.append(
            NewsItem(
                id=news_id_for(str(url)),
                source_id=source.id,
                title=str(title).strip(),
                url=str(url),
                summary=None,
                published_at=published,
                observed_at=now,
            )
        )
    return items


async def sweep_news(
    config: NewsSourcesConfig,
    client: Any,
    now: datetime,
) -> NewsSweepResult:
    result = NewsSweepResult()
    for source in config.sources:
        if not source.enabled:
            continue
        try:
            response = await client.get(source.url)
            response.raise_for_status()
            if source.kind == "rss":
                items = _parse_rss(response.text, source, now)
            else:
                items = _parse_hn(response.json(), source, now)
            result.items.extend(items)
            result.outcomes[source.id] = {
                "count": len(items),
                "status": "ok" if items else "empty",
            }
        except Exception as exc:
            logger.warning("News source %s failed: %s", source.id, exc)
            result.outcomes[source.id] = {"count": 0, "status": "error"}
    return result
