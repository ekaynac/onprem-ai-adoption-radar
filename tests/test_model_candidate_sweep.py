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
    def __init__(self, items): self._items = items
    async def get(self, url, **kwargs): return _Resp(self._items)


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
    rows = await sweep_model_candidates([], _Boom(), NOW)
    assert rows == []   # discover_trending_models is best-effort → []
