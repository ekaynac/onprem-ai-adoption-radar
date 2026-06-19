"""Discover candidate tools from GitHub repos linked in HF daily papers.

Pulls the Hugging Face daily-papers feed, resolves each paper's linked GitHub
repo, drops repos already tracked or below the star floor, best-effort maps the
paper's tags to a radar category (flagging needs-triage when unsure), and
returns proposals. Network failures degrade to "no proposals". Results are only
ever written to the review file (see proposals.py) — never auto-added.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from radar.discovery.proposals import SeedProposal
from radar.models import Category, SourceConfig
from radar.web.slugs import project_slug


logger = logging.getLogger(__name__)

HF_DAILY_PAPERS_URL = "https://huggingface.co/api/daily_papers"
GITHUB_REPO_URL = "https://api.github.com/repos/{full_name}"
_GITHUB_RE = re.compile(r"github\.com/([^/\s]+)/([^/\s#?]+)")

# Tag/topic keyword → category. First match wins; no match → triage fallback.
_CATEGORY_KEYWORDS: dict[str, Category] = {
    "coding": Category.CODING_AGENTS,
    "mcp": Category.MCP_TOOLING,
    "model-context-protocol": Category.MCP_TOOLING,
    "sandbox": Category.SANDBOX_GOVERNANCE,
    "agent-framework": Category.AGENT_FRAMEWORKS,
    "agent": Category.GENERAL_AGENTS,
    "serving": Category.MODEL_SERVING,
    "inference": Category.MODEL_SERVING,
    "infrastructure": Category.AI_INFRASTRUCTURE,
    "robot": Category.PHYSICAL_AI_INFRASTRUCTURE,
    "embodied": Category.PHYSICAL_AI_INFRASTRUCTURE,
}
_TRIAGE_FALLBACK = Category.MODEL_SERVING


def map_category(tags: list[str]) -> tuple[Category, bool]:
    """Best-effort (category, needs_triage). Unmatched → fallback + triage=True."""
    for tag in tags:
        low = tag.lower()
        for keyword, category in _CATEGORY_KEYWORDS.items():
            if keyword in low:
                return category, False
    return _TRIAGE_FALLBACK, True


async def discover_from_hf_papers(
    tracked_sources: list[SourceConfig],
    client: Any,
    min_stars: int = 500,
    headers: dict[str, str] | None = None,
) -> list[SeedProposal]:
    tracked = _tracked_repos(tracked_sources)
    items = await _daily_papers(client)
    by_url: dict[str, SeedProposal] = {}
    for item in items:
        paper = item.get("paper") or item
        full_name = _github_full_name(paper)
        if not full_name or full_name.lower() in tracked:
            continue
        repo = await _repo(client, full_name, headers)
        stars = int((repo or {}).get("stargazers_count") or 0)
        if repo is None or stars < min_stars:
            continue
        category, triage = map_category(
            list(paper.get("tags") or []) + list(repo.get("topics") or [])
        )
        name = repo.get("name") or full_name.split("/")[-1]
        url = repo.get("html_url") or f"https://github.com/{full_name}"
        if url in by_url:
            continue
        tags = list(repo.get("topics") or [])[:5]
        if triage:
            tags = ["needs-triage", *tags][:5]
        by_url[url] = SeedProposal(
            project=name,
            category=category,
            url=url,
            stars=stars,
            description=(repo.get("description") or "")[:200],
            suggested_id=f"github-{project_slug(name)}",
            suggested_tags=tags,
        )
    return sorted(by_url.values(), key=lambda p: p.stars, reverse=True)


async def _daily_papers(client: Any) -> list[dict[str, Any]]:
    try:
        response = await client.get(HF_DAILY_PAPERS_URL)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else (payload.get("papers") or [])
    except Exception as exc:
        logger.warning("HF daily-papers fetch failed: %s", exc)
        return []


async def _repo(client: Any, full_name: str, headers: dict[str, str] | None) -> dict[str, Any] | None:
    try:
        response = await client.get(
            GITHUB_REPO_URL.format(full_name=full_name), headers=headers or {}
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        logger.warning("GitHub repo lookup failed (%s): %s", full_name, exc)
        return None


def _github_full_name(paper: dict[str, Any]) -> str | None:
    candidate = paper.get("githubRepo") or paper.get("github") or ""
    if not candidate:
        for value in paper.values():
            if isinstance(value, str) and "github.com/" in value:
                candidate = value
                break
    match = _GITHUB_RE.search(str(candidate))
    if not match:
        return None
    owner, repo = match.group(1), match.group(2)
    return f"{owner}/{repo.removesuffix('.git')}"


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
