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


def test_server_registers_device_tools(tmp_path: Path):
    _seed_models(tmp_path)
    names = {t.name for t in asyncio.run(build_mcp_server(tmp_path).list_tools())}
    assert {"list_devices", "can_run", "fit_report"} <= names


def _seed_techniques(root: Path) -> None:
    from radar.models import Category, Ring
    from radar.research_radar.entities import OnPremImpact, TechniqueDomain, TechniqueEntry
    from radar.storage.run_store import RunStore

    (root / "data").mkdir(parents=True, exist_ok=True)
    entry = TechniqueEntry(
        id="speculative-decoding", name="Speculative Decoding",
        category=Category.MODEL_SERVING, domain=TechniqueDomain.INFERENCE,
        onprem_impact=OnPremImpact.REDUCES_LATENCY, ring=Ring.ADOPT, score=4.3,
        citation_count=1697,
    )
    store = RunStore(root / "data" / "runs")
    run_id = store.create_run()
    store.save_stage(run_id, "technique_cards", [entry.model_dump(mode="json")])
    store.update_meta(run_id, {"kind": "research", "technique_count": 1})


def test_server_registers_technique_tools(tmp_path: Path):
    _seed_techniques(tmp_path)
    server = build_mcp_server(tmp_path)

    names = {t.name for t in asyncio.run(server.list_tools())}

    assert {"list_techniques", "get_technique", "technique_movers"} <= names


def test_list_techniques_tool_returns_compact_rows(tmp_path: Path):
    _seed_techniques(tmp_path)
    server = build_mcp_server(tmp_path)

    result = asyncio.run(server.call_tool("list_techniques", {"ring": "adopt"}))
    payload = result[1].get("result", result[1])

    assert any(item["id"] == "speculative-decoding" for item in payload)


def test_get_technique_tool_full_payload(tmp_path: Path):
    _seed_techniques(tmp_path)
    server = build_mcp_server(tmp_path)

    result = asyncio.run(server.call_tool("get_technique",
                                          {"technique_id": "speculative-decoding"}))
    payload = result[1].get("result", result[1])

    assert payload["citation_count"] == 1697
    assert "momentum" in payload


def _seed_trending(root: Path) -> None:
    from datetime import UTC, datetime

    from radar.discovery.trending_entities import Lane, TrendingObservation
    from radar.storage.trending_observations_log import append_observations

    (root / "data").mkdir(parents=True, exist_ok=True)
    rows = [
        TrendingObservation(
            repo="acme/rocket", lane=Lane.ONPREM, stars=stars,
            observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
            repo_created_at=datetime(2026, 6, 1, tzinfo=UTC),
            description="d", topics=["llm"], license="MIT",
        )
        for day, stars in ((1, 100), (4, 500))
    ]
    append_observations(root / "data" / "trending-observations.jsonl", rows)


def test_server_registers_trending_tool(tmp_path: Path):
    _seed_trending(tmp_path)
    server = build_mcp_server(tmp_path)

    names = {t.name for t in asyncio.run(server.list_tools())}

    assert "list_trending" in names


def test_list_trending_tool_returns_rows(tmp_path: Path):
    _seed_trending(tmp_path)
    server = build_mcp_server(tmp_path)

    result = asyncio.run(server.call_tool("list_trending", {"lane": "onprem"}))
    payload = result[1].get("result", result[1])

    assert any(item["repo"] == "acme/rocket" for item in payload)
