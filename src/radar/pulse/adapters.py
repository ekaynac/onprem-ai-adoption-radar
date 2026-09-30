"""Repo and news lanes read the observation logs the publish pipeline already
writes every two hours (``data/trending-observations.jsonl``,
``data/news-observations.jsonl``). No new network code: the collectors work;
their output was just never turned into a "what's new" list.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from radar.pulse.items import Lane, PulseItem


logger = logging.getLogger(__name__)

_SECONDS_PER_DAY = 86_400.0


def repo_items(path: Path, now: datetime, window_days: int) -> list[PulseItem]:
    """Latest observation per repo created inside the window, with star velocity."""
    since = now - timedelta(days=window_days)
    latest: dict[str, dict[str, Any]] = {}
    first_seen: dict[str, datetime] = {}
    for row in _rows(path):
        repo = row.get("repo")
        observed = _parse_dt(row.get("observed_at"))
        created = _parse_dt(row.get("repo_created_at"))
        if not isinstance(repo, str) or observed is None or created is None or created < since:
            continue
        first_seen[repo] = min(first_seen.get(repo, observed), observed)
        if repo not in latest or observed >= _parse_dt(latest[repo]["observed_at"]):  # type: ignore[operator]
            latest[repo] = row
    items = []
    for repo, row in latest.items():
        item = _repo_item(repo, row, first_seen[repo], now)
        if item is not None:
            items.append(item)
    return items


def news_items(path: Path, now: datetime, window_days: int) -> list[PulseItem]:
    since = now - timedelta(days=window_days)
    items: dict[str, PulseItem] = {}
    for row in _rows(path):
        published = _parse_dt(row.get("published_at"))
        observed = _parse_dt(row.get("observed_at")) or now
        if published is not None and published < since:
            continue
        item = _news_item(row, published, observed, now)
        if item is not None and item.key not in items:
            items[item.key] = item
    return list(items.values())


def _repo_item(
    repo: str, row: dict[str, Any], first_seen: datetime, now: datetime,
) -> PulseItem | None:
    created = _parse_dt(row.get("repo_created_at"))
    stars = row.get("stars")
    signals: dict[str, float] = {}
    if isinstance(stars, int) and created is not None:
        age_days = max((now - created).total_seconds() / _SECONDS_PER_DAY, 1.0)
        signals = {"stars": float(stars), "stars_per_day": round(stars / age_days, 1)}
    topics = tuple(t for t in row.get("topics") or () if isinstance(t, str))
    try:
        return PulseItem(
            lane=Lane.REPO,
            key=repo,
            title=repo,
            url=f"https://github.com/{repo}",
            source="github",
            published_at=created,
            first_seen=first_seen,
            last_seen=now,
            summary=_clean(row.get("description")),
            kind=row.get("lane") if isinstance(row.get("lane"), str) else None,
            signals=signals,
            tags=topics,
        )
    except ValidationError as exc:
        logger.warning("Dropping malformed trending row %s: %s", repo, exc)
        return None


def _news_item(
    row: dict[str, Any], published: datetime | None, observed: datetime, now: datetime,
) -> PulseItem | None:
    key, title, url = row.get("id"), row.get("title"), row.get("url")
    if not isinstance(key, str) or not isinstance(title, str) or not isinstance(url, str):
        return None
    try:
        return PulseItem(
            lane=Lane.NEWS,
            key=key,
            title=" ".join(title.split()),
            url=url,
            source=str(row.get("source_id") or "news"),
            published_at=published,
            first_seen=observed,
            last_seen=now,
            summary=_clean(row.get("summary")),
            kind=str(row.get("source_id") or "news"),
        )
    except ValidationError as exc:
        logger.warning("Dropping malformed news row %s: %s", key, exc)
        return None


def _rows(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        logger.warning("Pulse adapter input missing: %s", path)
        return
    with path.open(encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                logger.warning("Skipping corrupt line %d in %s: %s", line_no, path, exc)
                continue
            if isinstance(row, dict):
                yield row


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _clean(text: Any, limit: int = 400) -> str | None:
    if not isinstance(text, str) or not text.strip():
        return None
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"
