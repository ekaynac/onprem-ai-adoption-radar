from datetime import datetime, timezone
from pathlib import Path

import pytest

from radar.collectors.registry import build_collectors
from radar.collectors.rss import RSSCollector
from radar.models import Category, Config, SourceConfig, SourceType


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, text):
        self.text = text

    async def get(self, url, follow_redirects=True):
        return FakeResponse(self.text)


@pytest.mark.asyncio
async def test_rss_collector_fetches_feed_items():
    source = SourceConfig(
        id="rss-agent-blog",
        type=SourceType.RSS,
        enabled=True,
        project="Agent Blog",
        category=Category.MCP_TOOLING,
        url="https://example.com/feed.xml",
        tags=["mcp"],
    )
    feed = Path("tests/fixtures/rss_feed.xml").read_text(encoding="utf-8")
    collector = RSSCollector([source], client=FakeClient(feed))

    signals = await collector.fetch(datetime(2026, 6, 9, tzinfo=timezone.utc))

    assert len(signals) == 1
    assert signals[0].id == "rss:rss-agent-blog:https://example.com/mcp-approval"
    assert signals[0].title == "MCP server approval patterns"


def test_registry_builds_enabled_collectors():
    config = Config(
        sources=[
            SourceConfig(
                id="rss-agent-blog",
                type=SourceType.RSS,
                enabled=True,
                project="Agent Blog",
                category=Category.MCP_TOOLING,
                url="https://example.com/feed.xml",
            )
        ]
    )

    collectors = build_collectors(config, client=object())

    assert len(collectors) == 1
    assert collectors[0].__class__.__name__ == "RSSCollector"
