from __future__ import annotations

import pytest

from radar.discovery.hf_trending_models import (
    discover_trending_models,
    fetch_trending_models,
)
from radar.models_radar.entities import ModelSeed


# HF /api/models returns a list of dicts like this:
MODELS = [
    {"id": "Qwen/Qwen3-32B", "downloads": 900000, "likes": 1200, "pipeline_tag": "text-generation"},
    {"id": "meta-llama/Llama-3.3-70B-Instruct", "downloads": 500000, "likes": 900, "pipeline_tag": "text-generation"},
    {"id": "Qwen/Qwen3-8B", "downloads": 800000, "likes": 1100, "pipeline_tag": "text-generation"},  # already seeded
    {"id": "tiny/obscure-model", "downloads": 50, "likes": 1, "pipeline_tag": "text-generation"},     # below floor
]


class FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.last_params = None

    async def get(self, url, params=None, **kw):
        self.last_params = params
        return FakeResp(self.payload)


class BoomClient:
    async def get(self, url, **kw):
        raise RuntimeError("network down")


def _seeds():
    return [ModelSeed(id="qwen3-8b", name="Qwen3 8B", family="Qwen3", hf_repo="Qwen/Qwen3-8B")]


@pytest.mark.asyncio
async def test_fetch_trending_models_passes_params():
    client = FakeClient(MODELS)
    out = await fetch_trending_models(client, limit=10, pipeline_tag="text-generation")
    assert out == MODELS
    assert client.last_params["limit"] == 10
    assert client.last_params["pipeline_tag"] == "text-generation"
    assert client.last_params["sort"] == "trendingScore"


@pytest.mark.asyncio
async def test_discover_dedups_seeded_and_filters_floor_and_ranks():
    proposals = await discover_trending_models(_seeds(), FakeClient(MODELS), min_downloads=10000)
    ids = [p.hf_repo for p in proposals]
    assert "Qwen/Qwen3-8B" not in ids        # already seeded → dropped
    assert "tiny/obscure-model" not in ids    # below floor → dropped
    assert ids == ["Qwen/Qwen3-32B", "meta-llama/Llama-3.3-70B-Instruct"]  # ranked by downloads desc
    top = proposals[0]
    assert top.family == "Qwen" and top.modality == "text" and top.suggested_id == "hf-qwen3-32b"
    assert "900000" in top.reason


@pytest.mark.asyncio
async def test_discover_degrades_to_empty_on_failure():
    assert await discover_trending_models(_seeds(), BoomClient()) == []
