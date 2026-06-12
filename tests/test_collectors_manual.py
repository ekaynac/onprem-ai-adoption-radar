from datetime import UTC, datetime

import pytest

from radar.collectors.manual import ManualCollector
from radar.models import Category, SourceConfig, SourceType


@pytest.mark.asyncio
async def test_manual_collector_emits_one_signal():
    source = SourceConfig(
        id="mcp-docs",
        type=SourceType.MANUAL,
        enabled=True,
        project="Model Context Protocol",
        category=Category.MCP_TOOLING,
        url="https://modelcontextprotocol.io/docs/getting-started/intro",
        tags=["mcp", "protocol"],
    )
    collector = ManualCollector([source])

    signals = await collector.fetch(datetime(2026, 6, 10, tzinfo=UTC))

    assert len(signals) == 1
    assert signals[0].id == "manual:mcp-docs"
    assert signals[0].project == "Model Context Protocol"
    assert signals[0].signal_type == "manual_reference"
