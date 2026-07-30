from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from radar.intelligence.sources.announcements import (
    AnnouncementConfig,
    AnnouncementPageAdapter,
)


@pytest.mark.asyncio
async def test_announcement_page_uses_conditional_requests_and_body_cursor() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304, request=request)
        return httpx.Response(
            200,
            text='<a href="/blog/kimi-k3">Kimi K3</a>',
            headers={"ETag": '"v1"', "Last-Modified": "Thu, 30 Jul 2026 08:00:00 GMT"},
            request=request,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        adapter = AnnouncementPageAdapter(
            client,
            pages=[
                AnnouncementConfig(
                    id="moonshot-news",
                    url="https://moonshot.ai/news",
                    publisher_id="publisher:moonshot-ai",
                    official_domains=["moonshot.ai"],
                )
            ],
            clock=lambda: datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
        )
        first = await adapter.discover(datetime(2026, 7, 29, tzinfo=UTC))
        second = await adapter.discover(datetime(2026, 7, 29, tzinfo=UTC))

    assert [candidate.release_name for candidate in first] == ["Kimi K3"]
    assert second == []
    assert requests[1].headers["if-none-match"] == '"v1"'

