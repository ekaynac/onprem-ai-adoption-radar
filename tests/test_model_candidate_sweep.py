"""Sweep untracked trending HF models → observations (canned client)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from radar.discovery.model_candidate_sweep import sweep_model_candidates
from radar.models_radar.entities import ModelSeed


NOW = datetime(2026, 7, 8, 7, 0, tzinfo=UTC)


class _Resp:
    def __init__(self, items): self._items = items
    def raise_for_status(self): return None
    def json(self): return self._items


class _Client:
    def __init__(self, items):
        self._items = items
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append(kwargs.get("params", {}))
        return _Resp(self._items)


@pytest.mark.asyncio
async def test_sweep_maps_untracked_trending_to_observations():
    # discover_trending_models drops seeded repos; "tracked/m" is seeded, so excluded.
    items = [
        {"id": "acme/rocket", "downloads": 50000, "likes": 10, "pipeline_tag": "text-generation"},
        {"id": "tracked/m", "downloads": 90000, "likes": 3, "pipeline_tag": "text-generation"},
    ]
    seeds = [ModelSeed.model_validate({"id": "tracked-m", "name": "M", "family": "T",
                                       "hf_repo": "tracked/m"})]

    rows = await sweep_model_candidates(seeds, _Client(items), NOW)

    repos = {r.hf_repo for r in rows}
    assert "acme/rocket" in repos and "tracked/m" not in repos
    rocket = next(r for r in rows if r.hf_repo == "acme/rocket")
    assert rocket.downloads == 50000 and rocket.observed_at == NOW


@pytest.mark.asyncio
async def test_sweep_network_failure_degrades_empty():
    class _Boom:
        async def get(self, url, **kwargs): raise RuntimeError("down")
    health = {}
    rows = await sweep_model_candidates([], _Boom(), NOW, health=health)
    assert rows == []   # discover_trending_models is best-effort → []
    assert health == {"requests": 18, "failures": 18}


@pytest.mark.asyncio
async def test_sweep_covers_recent_multimodal_releases_below_trending_floor():
    client = _Client(
        [
            {
                "id": "moonshotai/Kimi-K3",
                "downloads": 2850,
                "likes": 4860,
                "pipeline_tag": "image-text-to-text",
                "createdAt": "2026-07-28T08:00:00.000Z",
                "lastModified": "2026-07-31T07:58:00.000Z",
            }
        ]
    )

    rows = await sweep_model_candidates([], client, NOW)

    assert [row.hf_repo for row in rows] == ["moonshotai/Kimi-K3"]
    assert rows[0].pipeline_tag == "image-text-to-text"
    assert rows[0].created_at == "2026-07-28T08:00:00.000Z"
    assert any(call["sort"] == "lastModified" for call in client.calls)
    assert any(
        call.get("pipeline_tag") == "image-text-to-text"
        for call in client.calls
    )
