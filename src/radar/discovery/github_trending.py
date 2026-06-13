"""Discover fast-rising GitHub repos in the radar's categories.

Queries the GitHub search API per category topic, drops repos already tracked
and those below a star floor, and returns ranked proposals. Network failures
degrade to "no proposals" with a warning — discovery is opportunistic, never
required. Results are only ever written to a review file (see proposals.py).
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from radar.discovery.proposals import SeedProposal
from radar.models import Category, SourceConfig


logger = logging.getLogger(__name__)

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
PER_PAGE = 20

# Topic queries per category. Deliberately conservative — discovery proposes,
# a human disposes, so precision matters more than recall.
DEFAULT_TOPICS_BY_CATEGORY: dict[Category, list[str]] = {
    Category.CODING_AGENTS: ["ai-coding-assistant", "coding-agent"],
    Category.GENERAL_AGENTS: ["ai-agents", "autonomous-agents"],
    Category.MCP_TOOLING: ["model-context-protocol", "mcp-server"],
    Category.SANDBOX_GOVERNANCE: ["ai-sandbox", "agent-sandbox"],
    Category.AGENT_FRAMEWORKS: ["agent-framework", "llm-framework"],
    Category.MODEL_SERVING: ["llm-inference", "model-serving"],
    Category.AI_INFRASTRUCTURE: ["llmops", "ai-infrastructure"],
    Category.PHYSICAL_AI_INFRASTRUCTURE: ["robotics", "embodied-ai"],
    Category.FUN_EXPERIMENTAL: ["generative-art", "local-llm"],
}


async def discover_trending(
    tracked_sources: list[SourceConfig],
    client: Any,
    categories: list[Category],
    min_stars: int = 500,
    since_days: int = 30,
    topics_by_category: dict[Category, list[str]] | None = None,
    headers: dict[str, str] | None = None,
) -> list[SeedProposal]:
    """Return ranked, deduped proposals for untracked trending repos."""
    topics_map = topics_by_category or DEFAULT_TOPICS_BY_CATEGORY
    tracked = _tracked_repos(tracked_sources)
    pushed_since = (datetime.now(UTC) - timedelta(days=since_days)).date().isoformat()

    by_url: dict[str, SeedProposal] = {}
    for category in categories:
        for topic in topics_map.get(category, []):
            query = f"topic:{topic} stars:>={min_stars} pushed:>={pushed_since}"
            items = await _search(client, query, headers)
            for item in items:
                proposal = _to_proposal(item, category, min_stars, tracked)
                if proposal is not None and proposal.url not in by_url:
                    by_url[proposal.url] = proposal
    return sorted(by_url.values(), key=lambda p: p.stars, reverse=True)


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
        logger.warning("GitHub discovery query failed (%s): %s", query, exc)
        return []


def _to_proposal(
    item: dict[str, Any],
    category: Category,
    min_stars: int,
    tracked: set[str],
) -> SeedProposal | None:
    full_name = (item.get("full_name") or "").lower()
    stars = int(item.get("stargazers_count") or 0)
    url = item.get("html_url") or ""
    if not full_name or not url or stars < min_stars or full_name in tracked:
        return None
    name = item.get("name") or full_name.split("/")[-1]
    return SeedProposal(
        project=name,
        category=category,
        url=url,
        stars=stars,
        description=(item.get("description") or "")[:200],
        suggested_id=f"github-{_slug(name)}",
        suggested_tags=list(item.get("topics") or [])[:5],
    )


def _tracked_repos(sources: list[SourceConfig]) -> set[str]:
    tracked: set[str] = set()
    for source in sources:
        parsed = urlparse(str(source.url))
        if parsed.netloc != "github.com":
            continue
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2:
            tracked.add(f"{parts[0]}/{parts[1]}".lower())
    return tracked


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
