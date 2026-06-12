"""GitHub repository release collector."""

from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from radar.collectors.base import BaseCollector
from radar.models import Signal, SourceConfig


logger = logging.getLogger(__name__)


class GitHubCollector(BaseCollector):
    """Collect release and repository snapshot signals from GitHub repositories."""

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
        """Fetch releases and repo snapshots for all enabled GitHub repo sources."""
        signals: list[Signal] = []
        for source in self.sources:
            if not source.enabled:
                continue
            owner_repo = self._owner_repo(str(source.url))
            if owner_repo is None:
                logger.warning("Skipping invalid GitHub URL for source %s", source.id)
                continue
            owner, repo = owner_repo
            repo_snapshot = await self._fetch_repo_snapshot(source, owner, repo, since)
            if repo_snapshot is not None:
                signals.append(repo_snapshot)
            snapshot_metadata = repo_snapshot.metadata if repo_snapshot else {}
            signals.extend(
                await self._fetch_releases(source, owner, repo, since, snapshot_metadata)
            )
        return signals

    async def _fetch_repo_snapshot(
        self,
        source: SourceConfig,
        owner: str,
        repo: str,
        since: datetime,
    ) -> Signal | None:
        url = f"{self.base_url}/repos/{owner}/{repo}"
        try:
            response = await self.client.get(
                url,
                headers=self._headers(),
                follow_redirects=True,
            )
            response.raise_for_status()
            payload = response.json()
        except (KeyError, httpx.HTTPError) as exc:
            logger.warning("GitHub repo snapshot %s failed: %s", source.id, exc)
            return None

        pushed_at_raw = payload.get("pushed_at")
        pushed_at = _parse_github_datetime(pushed_at_raw) or datetime.now(UTC)
        # Snapshots describe current repo posture. Emit them each scan, but preserve pushed_at
        # so downstream scoring/reporting can reason about maintenance velocity.
        metadata = {
            "repo": f"{owner}/{repo}",
            "stars": payload.get("stargazers_count", 0),
            "forks": payload.get("forks_count", 0),
            "open_issues": payload.get("open_issues_count", 0),
            "pushed_at": pushed_at_raw or "",
            "license": (payload.get("license") or {}).get("spdx_id") or "NOASSERTION",
            "topics": payload.get("topics") or [],
        }
        return Signal(
            id=f"github:{source.id}:repo_snapshot",
            source_id=source.id,
            project=source.project,
            category=source.category,
            title=f"{source.project} repository snapshot",
            url=payload.get("html_url") or str(source.url),
            published_at=max(pushed_at, since),
            raw_summary=(
                f"GitHub snapshot: {metadata['stars']} stars, {metadata['forks']} forks, "
                f"{metadata['open_issues']} open issues, license {metadata['license']}."
            ),
            signal_type="github_repo_snapshot",
            tags=source.tags,
            metadata=metadata,
        )

    async def _fetch_releases(
        self,
        source: SourceConfig,
        owner: str,
        repo: str,
        since: datetime,
        repo_snapshot: dict | None = None,
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
            # Draft releases have a null published_at; the API can also return
            # partial objects. Skip anything malformed instead of aborting the
            # whole collector run.
            published_at = _parse_github_datetime(release.get("published_at"))
            if published_at is None or published_at < since:
                continue
            tag = release.get("tag_name")
            release_id = release.get("id")
            if not tag or release_id is None:
                logger.warning(
                    "Skipping malformed release payload for source %s", source.id
                )
                continue
            body = release.get("body") or ""
            highlights = self.extract_release_highlights(body)
            signals.append(
                Signal(
                    id=f"github:{source.id}:release:{release_id}",
                    source_id=source.id,
                    project=source.project,
                    category=source.category,
                    title=f"{source.project} released {tag}",
                    url=release.get("html_url") or str(source.url),
                    published_at=published_at,
                    raw_summary="\n".join(highlights) if highlights else self._compact_text(body),
                    signal_type="github_release",
                    tags=source.tags,
                    metadata={
                        "repo": f"{owner}/{repo}",
                        "tag": tag,
                        "prerelease": release.get("prerelease", False),
                        "author": release.get("author", {}).get("login", ""),
                        "release_highlights": highlights,
                        "repo_snapshot": repo_snapshot or {},
                    },
                )
            )
        return signals

    @staticmethod
    def extract_release_highlights(body: str, limit: int = 5) -> list[str]:
        """Extract compact, report-safe highlights from GitHub release Markdown."""
        body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
        body = re.split(
            r"(?im)^\s{0,3}#{1,6}\s*(full changelog|contributors|new contributors)\b|\*\*full changelog\*\*:?",
            body,
            maxsplit=1,
        )[0]
        highlights: list[str] = []
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                continue
            if line.startswith(("http://", "https://")):
                continue
            line = re.sub(r"^[-*+]\s+", "", line)
            line = re.sub(r"^\d+[.)]\s+", "", line)
            line = re.sub(r"^\[(?:fixed|added|changed|removed|security)\]\s*", "", line, flags=re.I)
            # Keep the link text, drop the URL — before stripping bare URLs,
            # which would otherwise leave dangling "[text](" fragments.
            line = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", line)
            line = re.sub(r"https?://\S+", "", line)
            # Stripping the PR URL leaves "by @user in" hanging at the end.
            line = re.sub(r"\s+by @[\w-]+\s+in\s*$", "", line)
            line = re.sub(r"\s+", " ", line).strip()
            line = line.strip("` -")
            if not line or line.lower().startswith(("compare:", "what's changed")):
                continue
            highlights.append(GitHubCollector._compact_text(line, max_chars=180))
            if len(highlights) >= limit:
                break
        if highlights:
            return highlights
        compact = GitHubCollector._compact_text(body, max_chars=240)
        return [compact] if compact else []

    @staticmethod
    def _compact_text(text: str, max_chars: int = 500) -> str:
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
        text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"[#>*_`]+", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 1].rstrip() + "…"

    @staticmethod
    def _owner_repo(url: str) -> tuple[str, str] | None:
        parsed = urlparse(url)
        parts = [part for part in parsed.path.split("/") if part]
        if parsed.netloc != "github.com" or len(parts) < 2:
            return None
        return parts[0], parts[1]


def _parse_github_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
