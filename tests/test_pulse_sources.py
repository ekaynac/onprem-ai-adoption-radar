"""Pulse collectors against real Hub payloads (recorded 2026-09-30)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from radar.pulse.items import Lane
from radar.pulse.sources import fetch_daily_papers, fetch_lab_models, model_item, paper_item


FIXTURES = Path(__file__).parent / "fixtures" / "pulse"
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
LABS = frozenset({"Qwen", "deepseek-ai"})


def _load(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_model_rows_map_to_items_with_origin() -> None:
    items = {
        item.key: item
        for row in _load("hf_models_2026-09-30.json")
        if (item := model_item(row, LABS, NOW)) is not None
    }

    image = items["Qwen/Qwen-Image-2.1"]
    assert image.lane is Lane.MODEL
    assert image.kind == "original"
    assert str(image.url) == "https://huggingface.co/Qwen/Qwen-Image-2.1"
    assert image.signals["likes"] > 0
    assert image.published_at is not None and image.published_at.year == 2026
    assert items["Qwen/Qwen3.8-Flash-Next-FP8"].kind == "variant"
    gguf = items["unsloth/DeepSeek-V4-Flash-Vision-Exp-GGUF"]
    assert gguf.kind == "derivative"
    assert gguf.parent == "deepseek-ai/DeepSeek-V4-Flash-Vision-Exp"


def test_private_and_malformed_model_rows_are_dropped() -> None:
    assert model_item({"id": "Qwen/secret", "private": True}, LABS, NOW) is None
    assert model_item({"id": "no-slash"}, LABS, NOW) is None
    assert model_item({}, LABS, NOW) is None


def test_paper_rows_map_to_arxiv_items() -> None:
    items = [
        item for row in _load("hf_daily_papers_2026-09-30.json")
        if (item := paper_item(row, NOW)) is not None
    ]

    assert len(items) == 3
    first = items[0]
    assert first.lane is Lane.PAPER
    assert str(first.url).startswith("https://arxiv.org/abs/")
    assert first.signals["has_code"] == 1.0
    assert first.summary is not None and len(first.summary) <= 400


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_fetch_lab_models_reports_per_org_failures() -> None:
    rows = _load("hf_models_2026-09-30.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["author"] == "deepseek-ai":
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json=[r for r in rows if r["id"].startswith("Qwen/")])

    async def run():
        async with _client(handler) as client:
            return await fetch_lab_models(client, ["Qwen", "deepseek-ai"], 20, LABS, NOW)

    result = asyncio.run(run())

    assert result.requests == 2
    assert result.status == "partial"
    assert any("deepseek-ai" in e for e in result.errors)
    assert {i.key.split("/")[0] for i in result.items} == {"Qwen"}


def test_fetch_daily_papers_surfaces_a_dead_source() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "rate limited"})

    async def run():
        async with _client(handler) as client:
            return await fetch_daily_papers(client, 100, NOW)

    result = asyncio.run(run())

    assert result.items == ()
    assert result.status == "error"
