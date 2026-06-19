from datetime import UTC, datetime
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
        self.headers_seen: list[dict | None] = []

    async def get(self, url, headers=None, follow_redirects=True):
        self.headers_seen.append(headers)
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

    signals = await collector.fetch(datetime(2026, 6, 9, tzinfo=UTC))

    assert len(signals) == 1
    assert signals[0].id == "rss:rss-agent-blog:https://example.com/mcp-approval"
    assert signals[0].title == "MCP server approval patterns"
    # A browser-like User-Agent is sent so bot-protected hosts return the feed.
    assert collector.client.headers_seen[0]["User-Agent"].startswith("Mozilla/5.0")


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


@pytest.mark.asyncio
async def test_unparseable_entry_date_falls_back_instead_of_crashing():
    feed = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Blog</title>
<item><title>Good post</title><link>https://example.com/good</link>
<pubDate>liberation day</pubDate></item>
</channel></rss>"""
    source = SourceConfig(
        id="rss-agent-blog",
        type=SourceType.RSS,
        enabled=True,
        project="Agent Blog",
        category=Category.MCP_TOOLING,
        url="https://example.com/feed.xml",
    )
    collector = RSSCollector([source], client=FakeClient(feed))

    signals = await collector.fetch(datetime(2026, 6, 9, tzinfo=UTC))

    # Entry with an unparseable date falls back to "now" and is kept.
    assert [s.title for s in signals] == ["Good post"]


@pytest.mark.asyncio
async def test_broken_feed_logs_warning_instead_of_silence(caplog):
    source = SourceConfig(
        id="rss-agent-blog",
        type=SourceType.RSS,
        enabled=True,
        project="Agent Blog",
        category=Category.MCP_TOOLING,
        url="https://example.com/feed.xml",
    )
    collector = RSSCollector([source], client=FakeClient("<html>502 Bad Gateway</html>"))

    import logging

    with caplog.at_level(logging.WARNING, logger="radar.collectors.rss"):
        signals = await collector.fetch(datetime(2026, 6, 9, tzinfo=UTC))

    assert signals == []
    assert any("rss-agent-blog" in record.getMessage() for record in caplog.records)
    # Parse failures are also surfaced on the collector so the orchestrator can
    # fold them into the run's collector_warnings (not just the logger).
    assert collector.warnings
    assert "rss-agent-blog" in collector.warnings[0]
