from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from radar.intelligence.contracts import EvidenceStrength
from radar.intelligence.sources.github import GitHubReleaseAdapter


NOW = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_github_official_org_release_is_public_discovery() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/orgs/moonshotai/repos"):
            return httpx.Response(
                200,
                json=[
                    {
                        "full_name": "MoonshotAI/Kimi-K3",
                        "name": "Kimi-K3",
                        "html_url": "https://github.com/MoonshotAI/Kimi-K3",
                        "pushed_at": "2026-07-30T08:00:00Z",
                    }
                ],
                request=request,
            )
        if request.url.path.endswith("/releases"):
            return httpx.Response(
                200,
                json=[{"tag_name": "v1.0.0", "published_at": "2026-07-30T08:00:00Z"}],
                request=request,
            )
        if request.url.path.endswith("/tags"):
            return httpx.Response(200, json=[{"name": "v1.0.0"}], request=request)
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        adapter = GitHubReleaseAdapter(
            client,
            organizations={"MoonshotAI": "publisher:moonshot-ai"},
            clock=lambda: NOW,
        )
        candidates = await adapter.discover(
            datetime(2026, 7, 29, tzinfo=UTC)
        )

    kimi = next(
        candidate
        for candidate in candidates
        if candidate.external_id == "MoonshotAI/Kimi-K3"
    )
    assert kimi.source_record.strength is EvidenceStrength.OFFICIAL_REPOSITORY
    assert kimi.publisher_hint == "publisher:moonshot-ai"
    assert kimi.claims["release_tags"] == ["v1.0.0"]

