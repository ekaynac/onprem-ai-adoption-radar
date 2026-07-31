"""Official GitHub organization release discovery."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from radar.intelligence.contracts import EvidenceStrength
from radar.intelligence.sources.base import DiscoveryCandidate, SourceRecord
from radar.intelligence.sources.utils import parse_datetime


class GitHubReleaseAdapter:
    id = "github-releases"

    def __init__(
        self,
        client: httpx.AsyncClient,
        organizations: dict[str, str],
        *,
        source_id: str = "github-releases",
        clock: Callable[[], datetime] | None = None,
    ):
        self.client = client
        self.organizations = {
            key.casefold(): value for key, value in organizations.items()
        }
        self.id = source_id
        self.clock = clock or (lambda: datetime.now(UTC))
        self.remaining_quota: int | None = None
        self.warnings: list[str] = []

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "onprem-ai-adoption-radar",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = os.getenv("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def discover(self, since: datetime) -> list[DiscoveryCandidate]:
        candidates: list[DiscoveryCandidate] = []
        for organization, publisher_id in sorted(self.organizations.items()):
            response = await self.client.get(
                f"https://api.github.com/orgs/{organization}/repos",
                params={
                    "sort": "pushed",
                    "direction": "desc",
                    "per_page": 100,
                },
                headers=self._headers(),
            )
            response.raise_for_status()
            self._capture_quota(response)
            record = self._record(response)
            repositories = response.json()
            if not isinstance(repositories, list):
                raise ValueError("GitHub organization repositories must be a list")
            for repository in repositories:
                if not isinstance(repository, dict):
                    continue
                pushed_at = parse_datetime(repository.get("pushed_at"))
                if pushed_at is None or pushed_at < since:
                    continue
                full_name = str(repository["full_name"])
                claims = await self._release_claims(full_name)
                candidates.append(
                    DiscoveryCandidate(
                        source_record=record,
                        external_id=full_name,
                        publisher_hint=publisher_id,
                        release_name=str(repository["name"]),
                        artifact_urls=[str(repository["html_url"])],
                        claims={
                            "pushed_at": pushed_at.isoformat(),
                            **claims,
                        },
                    )
                )
        return sorted(
            candidates,
            key=lambda candidate: candidate.external_id.casefold(),
        )

    async def fetch(self, url: str) -> SourceRecord:
        response = await self.client.get(url, headers=self._headers())
        response.raise_for_status()
        self._capture_quota(response)
        return self._record(response)

    async def _release_claims(self, full_name: str) -> dict[str, Any]:
        base_url = f"https://api.github.com/repos/{full_name}"
        releases_response = await self.client.get(
            f"{base_url}/releases",
            params={"per_page": 20},
            headers=self._headers(),
        )
        tags_response = await self.client.get(
            f"{base_url}/tags",
            params={"per_page": 20},
            headers=self._headers(),
        )
        release_tags: set[str] = set()
        releases: list[dict[str, Any]] = []
        if releases_response.status_code < 400:
            self._capture_quota(releases_response)
            payload = releases_response.json()
            if isinstance(payload, list):
                releases = [item for item in payload if isinstance(item, dict)]
                release_tags.update(
                    str(item["tag_name"])
                    for item in releases
                    if item.get("tag_name")
                )
        else:
            self.warnings.append(
                f"{full_name}: releases returned {releases_response.status_code}"
            )
        if tags_response.status_code < 400:
            self._capture_quota(tags_response)
            payload = tags_response.json()
            if isinstance(payload, list):
                release_tags.update(
                    str(item["name"])
                    for item in payload
                    if isinstance(item, dict) and item.get("name")
                )
        else:
            self.warnings.append(
                f"{full_name}: tags returned {tags_response.status_code}"
            )
        return {
            "release_tags": sorted(release_tags),
            "releases": releases,
        }

    def _record(self, response: httpx.Response) -> SourceRecord:
        return SourceRecord.from_bytes(
            source_id=self.id,
            url=str(response.request.url),
            body=response.content,
            retrieved_at=self.clock(),
            strength=EvidenceStrength.OFFICIAL_REPOSITORY,
            content_type=response.headers.get("content-type"),
        )

    def _capture_quota(self, response: httpx.Response) -> None:
        raw = response.headers.get("x-ratelimit-remaining")
        if raw is not None and raw.isdigit():
            self.remaining_quota = int(raw)
