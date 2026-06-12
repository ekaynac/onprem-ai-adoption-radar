"""Tests for the MCP server adapter wiring."""

from __future__ import annotations

import asyncio
from pathlib import Path

from radar.mcp_server.server import build_mcp_server
from radar.models import Category, DecisionCard, Ring
from radar.storage.database import RadarDatabase


def _seed(tmp_path: Path) -> None:
    db = RadarDatabase(tmp_path / "data" / "radar.db")
    db.initialize()
    db.upsert_cards(
        [
            DecisionCard(
                project="vLLM",
                category=Category.MODEL_SERVING,
                ring=Ring.ADOPT,
                summary="fast inference",
                workflow_fit={},
                risk_level="low",
            )
        ]
    )


def test_server_registers_expected_tools(tmp_path: Path):
    _seed(tmp_path)
    server = build_mcp_server(tmp_path)

    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert {"list_recommendations", "get_project", "list_tracked_projects"} <= names


def test_list_recommendations_tool_returns_seeded_card(tmp_path: Path):
    _seed(tmp_path)
    server = build_mcp_server(tmp_path)

    result = asyncio.run(server.call_tool("list_recommendations", {"rings": ["adopt"]}))
    # FastMCP returns (content, structured) — inspect the structured payload.
    structured = result[1]
    payload = structured.get("result", structured)
    assert any(item["project"] == "vLLM" for item in payload)
