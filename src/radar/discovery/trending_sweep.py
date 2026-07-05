"""Two-lane GitHub sweep for trending repos → observations.

The strict `onprem` lane matches the radar's identity (drives the autopilot);
the `broader` lane catches general AI heat (content only). Each lane runs two
query shapes: rising (established + still-pushed) and born-recently (young).
Every query is best-effort — a failure skips that query with a warning, never
raising. Tracked sources are excluded; onprem wins repos seen in both lanes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from dateutil import parser as date_parser

from radar.discovery.trending_entities import Lane, TrendingObservation
from radar.models import SourceConfig


logger = logging.getLogger(__name__)

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
PER_PAGE = 30
PER_LANE_CAP = 20
RISING_MIN_STARS = 800
BORN_MIN_STARS = 50
BORN_WINDOW_DAYS = 14
PUSHED_WINDOW_DAYS = 30

ONPREM_TOPICS = [
    "llm-inference", "model-serving", "ai-agents", "agent-framework",
    "mcp-server", "model-context-protocol", "local-llm", "self-hosted-ai",
    "llmops", "ai-sandbox",
]
BROADER_TOPICS = [
    "llm", "generative-ai", "large-language-models", "ai",
]


async def sweep_trending(
    tracked_sources: list[SourceConfig],
    client: Any,
    now: datetime,
    headers: dict[str, str] | None = None,
) -> list[TrendingObservation]:
    tracked = _tracked_repos(tracked_sources)
    pushed_since = (now - timedelta(days=PUSHED_WINDOW_DAYS)).date().isoformat()
    born_since = (now - timedelta(days=BORN_WINDOW_DAYS)).date().isoformat()

    seen: set[str] = set()
    observations: list[TrendingObservation] = []
    # onprem first so it wins repos that also match a broader topic.
    for lane, topics in ((Lane.ONPREM, ONPREM_TOPICS), (Lane.BROADER, BROADER_TOPICS)):
        lane_repos: set[str] = set()
        for topic in topics:
            if len(lane_repos) >= PER_LANE_CAP:
                break
            queries = [
                f"topic:{topic} stars:>={RISING_MIN_STARS} pushed:>={pushed_since}",
                f"topic:{topic} created:>={born_since} stars:>={BORN_MIN_STARS}",
            ]
            for query in queries:
                if len(lane_repos) >= PER_LANE_CAP:
                    break
                for item in await _search(client, query, headers):
                    repo = (item.get("full_name") or "").strip()
                    if not repo or repo.lower() in tracked or repo in seen:
                        continue
                    observation = _to_observation(item, lane, now)
                    if observation is None:
                        continue
                    seen.add(repo)
                    lane_repos.add(repo)
                    observations.append(observation)
                    if len(lane_repos) >= PER_LANE_CAP:
                        break
    return observations


async def _search(
    client: Any, query: str, headers: dict[str, str] | None
) -> list[dict[str, Any]]:
    try:
        response = await client.get(
            GITHUB_SEARCH_URL,
            params={"q": query, "sort": "stars", "order": "desc", "per_page": PER_PAGE},
            headers=headers or {},
        )
        response.raise_for_status()
        return response.json().get("items") or []
    except Exception as exc:
        logger.warning("Trending sweep query failed (%s): %s", query, exc)
        return []


def _to_observation(
    item: dict[str, Any], lane: Lane, now: datetime
) -> TrendingObservation | None:
    repo = (item.get("full_name") or "").strip()
    created_raw = item.get("created_at")
    if not repo or not created_raw:
        return None
    try:
        created = date_parser.parse(created_raw)
    except (ValueError, OverflowError):
        return None
    spdx = (item.get("license") or {}).get("spdx_id")
    return TrendingObservation(
        repo=repo, lane=lane, stars=int(item.get("stargazers_count") or 0),
        observed_at=now, repo_created_at=created,
        description=(item.get("description") or "")[:200],
        topics=list(item.get("topics") or [])[:8],
        license=None if spdx in (None, "NOASSERTION") else spdx,
    )


def _tracked_repos(sources: list[SourceConfig]) -> set[str]:
    """owner/name (lowercased) for every github.com source — mirror of github_trending."""
    tracked: set[str] = set()
    for source in sources:
        parsed = urlparse(str(source.url))
        if parsed.netloc != "github.com":
            continue
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2:
            tracked.add(f"{parts[0]}/{parts[1]}".lower())
    return tracked
