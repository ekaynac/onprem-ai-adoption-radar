"""New GitHub repositories, by topic, born inside the Pulse window.

One search per topic: ``topic:<t> created:>=<window start> stars:>=<min>``,
sorted by stars. Velocity is stars per day since creation, so a single
observation is enough; ``first_seen`` comes from the item store.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError

from radar.pulse.http import get_with_retry
from radar.pulse.items import Lane, PulseItem
from radar.pulse.sources import SourceRun, error_text
from radar.pulse.text import shorten


logger = logging.getLogger(__name__)

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
PER_PAGE = 30
_SECONDS_PER_DAY = 86_400.0


def repo_item(raw: dict[str, Any], now: datetime) -> PulseItem | None:
    repo = raw.get("full_name")
    created_raw = raw.get("created_at")
    if not isinstance(repo, str) or "/" not in repo or not isinstance(created_raw, str):
        return None
    try:
        created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    stars = raw.get("stargazers_count")
    signals: dict[str, float] = {}
    if isinstance(stars, int) and not isinstance(stars, bool):
        age_days = max((now - created).total_seconds() / _SECONDS_PER_DAY, 1.0)
        signals = {"stars": float(stars), "stars_per_day": round(stars / age_days, 1)}
    # Same caps as the retired trending log (200 chars, 8 topics): they feed the
    # label content hash, so changing them would re-triage every repo once.
    topics = tuple(t for t in raw.get("topics") or () if isinstance(t, str))[:8]
    description = raw.get("description")
    try:
        return PulseItem(
            lane=Lane.REPO, key=repo, title=repo, url=f"https://github.com/{repo}",
            source="github", published_at=created, first_seen=now, last_seen=now,
            summary=shorten(description[:200] if isinstance(description, str) else None), signals=signals, tags=topics,
        )
    except ValidationError as exc:
        logger.warning("Dropping malformed GitHub repo %s: %s", repo, exc)
        return None


async def fetch_new_repos(
    client: Any,
    topics: Iterable[str],
    min_stars: int,
    window_days: int,
    now: datetime,
    headers: dict[str, str] | None = None,
) -> SourceRun:
    since = (now - timedelta(days=window_days)).date().isoformat()
    topic_list = list(topics)
    items: dict[str, PulseItem] = {}
    errors: list[str] = []
    for topic in topic_list:
        query = f"topic:{topic} created:>={since} stars:>={min_stars}"
        try:
            response = await get_with_retry(
                client, GITHUB_SEARCH_URL, label=f"github:{topic}",
                params={"q": query, "sort": "stars", "order": "desc", "per_page": PER_PAGE},
                headers=headers or {},
            )
            rows = response.json().get("items") or []
        except Exception as exc:
            errors.append(f"{topic}: {error_text(exc)}")
            continue
        for row in rows:
            item = repo_item(row, now) if isinstance(row, dict) else None
            if item is not None:
                items.setdefault(item.key, item)  # a repo matching two topics counts once
    return SourceRun("github:new-repos", tuple(items.values()), len(topic_list), tuple(errors))
