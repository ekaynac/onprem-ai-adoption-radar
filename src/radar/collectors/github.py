"""GitHub repository release collector."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from urllib.parse import urlparse

import httpx

from radar.collectors.base import BaseCollector
from radar.models import Signal, SourceConfig


logger = logging.getLogger(__name__)


class GitHubCollector(BaseCollector):
    """Collect release signals from configured GitHub repositories."""

    def __init__(self, sources: list[SourceConfig], client: httpx.AsyncClient):
        self.sources = sources
        self.client = client
        self.base_url = "https://api.github.com"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "onprem-ai-adoption-radar",
        }
        token = os.getenv("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def fetch(self, since: datetime) -> list[Signal]:
        """Fetch releases for all enabled GitHub repo sources."""
        signals: list[Signal] = []
        for source in self.sources:
            if not source.enabled:
                continue
            owner_repo = self._owner_repo(str(source.url))
            if owner_repo is None:
                logger.warning("Skipping invalid GitHub URL for source %s", source.id)
                continue
            owner, repo = owner_repo
            signals.extend(await self._fetch_releases(source, owner, repo, since))
        return signals

    async def _fetch_releases(
        self,
        source: SourceConfig,
        owner: str,
        repo: str,
        since: datetime,
    ) -> list[Signal]:
        url = f"{self.base_url}/repos/{owner}/{repo}/releases?per_page=10"
        try:
            response = await self.client.get(
                url,
                headers=self._headers(),
                follow_redirects=True,
            )
            response.raise_for_status()
            releases = response.json()
        except httpx.HTTPError as exc:
            logger.warning("GitHub source %s failed: %s", source.id, exc)
            return []

        signals: list[Signal] = []
        for release in releases:
            published_at = datetime.fromisoformat(
                release["published_at"].replace("Z", "+00:00")
            )
            if published_at < since:
                continue
            tag = release["tag_name"]
            signals.append(
                Signal(
                    id=f"github:{source.id}:release:{release['id']}",
                    source_id=source.id,
                    project=source.project,
                    category=source.category,
                    title=f"{source.project} released {tag}",
                    url=release["html_url"],
                    published_at=published_at,
                    raw_summary=release.get("body") or "",
                    signal_type="github_release",
                    tags=source.tags,
                    metadata={
                        "repo": f"{owner}/{repo}",
                        "tag": tag,
                        "prerelease": release.get("prerelease", False),
                        "author": release.get("author", {}).get("login", ""),
                    },
                )
            )
        return signals

    @staticmethod
    def _owner_repo(url: str) -> tuple[str, str] | None:
        parsed = urlparse(url)
        parts = [part for part in parsed.path.split("/") if part]
        if parsed.netloc != "github.com" or len(parts) < 2:
            return None
        return parts[0], parts[1]
