from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from radar.intelligence.contracts import EvidenceStrength
from radar.intelligence.sources.feeds import FeedConfig, OfficialFeedAdapter


FEED = b"""\
<?xml version="1.0"?>
<rss version="2.0"><channel><title>News</title>
<item><guid>kimi-k3</guid><title>Kimi K3 released</title>
<link>https://moonshot.ai/blog/kimi-k3#launch</link>
<pubDate>Thu, 30 Jul 2026 08:00:00 GMT</pubDate></item>
</channel></rss>
"""


@pytest.mark.asyncio
async def test_feed_entry_outside_official_domain_stays_internal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=FEED,
            headers={"Content-Type": "application/rss+xml"},
            request=request,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        adapter = OfficialFeedAdapter(
            client,
            feeds=[
                FeedConfig(
                    id="moonshot",
                    url="https://news.example.net/moonshot.xml",
                    publisher_id="publisher:moonshot-ai",
                    official_domains=["moonshot.ai"],
                )
            ],
            clock=lambda: datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
        )
        candidate = (
            await adapter.discover(datetime(2026, 7, 29, tzinfo=UTC))
        )[0]

    assert candidate.source_record.strength is EvidenceStrength.AGGREGATOR
    assert candidate.external_id == "kimi-k3"
    assert candidate.artifact_urls == ["https://moonshot.ai/blog/kimi-k3"]


@pytest.mark.asyncio
async def test_official_feed_domain_is_public_announcement() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=FEED, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        adapter = OfficialFeedAdapter(
            client,
            feeds=[
                FeedConfig(
                    id="moonshot",
                    url="https://moonshot.ai/feed.xml",
                    publisher_id="publisher:moonshot-ai",
                    official_domains=["moonshot.ai"],
                )
            ],
        )
        candidate = (
            await adapter.discover(datetime(2026, 7, 29, tzinfo=UTC))
        )[0]

    assert (
        candidate.source_record.strength
        is EvidenceStrength.OFFICIAL_ANNOUNCEMENT
    )

