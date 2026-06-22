"""Tests for the MCP server adapter wiring."""

from __future__ import annotations

import asyncio
from pathlib import Path

from radar.mcp_server.server import build_mcp_server
from radar.models import Category, DecisionCard, Ring
from radar.storage.database import RadarDatabase
from radar.storage.run_store import RunStore


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


def _seed_models(tmp_path: Path):
    from radar.models import Ring
    from radar.models_radar.entities import (
        HardwareTier,
        Modality,
        ModelEntry,
        Openness,
        Platform,
        QuantVariant,
    )
    rs = RunStore(tmp_path / "data" / "runs")
    rid = rs.create_run()
    e = ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3", params_total=8_000_000_000,
                   openness=Openness.OPEN_PERMISSIVE, hardware_tier=HardwareTier.LAPTOP,
                   ring=Ring.ADOPT, score=4.0, modality=Modality.TEXT,
                   quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5,
                                        est_memory_gb_4k=8.0, platform=Platform.GENERIC, source="hf:x")])
    rs.save_stage(rid, "model_cards", [e.model_dump(mode="json")])
    rs.update_meta(rid, {"kind": "models", "model_count": 1})


def test_server_registers_model_tools(tmp_path: Path):
    _seed_models(tmp_path)
    server = build_mcp_server(tmp_path)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"list_models", "get_model", "model_movers"} <= names


def test_list_models_tool_filters_by_memory(tmp_path: Path):
    _seed_models(tmp_path)
    server = build_mcp_server(tmp_path)
    result = asyncio.run(server.call_tool("list_models", {"max_memory_gb": 24}))
    payload = result[1].get("result", result[1])
    assert any(item["id"] == "qwen3-8b" for item in payload)
