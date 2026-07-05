"""Two-lane GitHub sweep → trending observations (canned search fixtures)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from radar.discovery.trending_entities import Lane
from radar.discovery.trending_sweep import sweep_trending
from radar.models import Category, SourceConfig, SourceType


NOW = datetime(2026, 7, 5, 7, 0, tzinfo=UTC)


def _item(full_name: str, stars: int, created: str = "2026-06-01T00:00:00Z",
          spdx: str | None = "Apache-2.0") -> dict[str, Any]:
    return {
        "full_name": full_name, "stargazers_count": stars,
        "created_at": created, "pushed_at": "2026-07-04T00:00:00Z",
        "html_url": f"https://github.com/{full_name}",
        "description": "d", "topics": ["llm", "inference"],
        "license": {"spdx_id": spdx} if spdx is not None else None,
    }


class _Client:
    """Returns items per query substring; records queries; can fail one query."""

    def __init__(self, by_topic: dict[str, list[dict]], fail_substr: str | None = None):
        self._by_topic = by_topic
        self._fail = fail_substr
        self.queries: list[str] = []

    async def get(self, url, **kwargs):
        query = kwargs.get("params", {}).get("q", "")
        self.queries.append(query)
        if self._fail and self._fail in query:
            raise RuntimeError("boom")
        items: list[dict] = []
        for topic, rows in self._by_topic.items():
            if f"topic:{topic}" in query:
                items = rows
                break
        return _Resp(items)


class _Resp:
    def __init__(self, items):
        self._items = items
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"items": self._items}


def _tracked(full_name: str) -> SourceConfig:
    return SourceConfig(
        id=f"github-{full_name.split('/')[-1]}", type=SourceType.GITHUB_REPO,
        project=full_name.split("/")[-1], category=Category.MODEL_SERVING,
        url=f"https://github.com/{full_name}",
    )


@pytest.mark.asyncio
async def test_sweep_maps_items_to_observations():
    client = _Client({"llm-inference": [_item("acme/rocket", 1500)]})

    observations = await sweep_trending([], client, NOW)

    rocket = next(o for o in observations if o.repo == "acme/rocket")
    assert rocket.lane == Lane.ONPREM
    assert rocket.stars == 1500
    assert rocket.observed_at == NOW
    assert rocket.license == "Apache-2.0"
    assert rocket.repo_created_at.year == 2026


@pytest.mark.asyncio
async def test_sweep_excludes_tracked_repos():
    client = _Client({"llm-inference": [_item("acme/rocket", 1500),
                                         _item("tracked/tool", 2000)]})

    observations = await sweep_trending([_tracked("tracked/tool")], client, NOW)

    assert {o.repo for o in observations} == {"acme/rocket"}


@pytest.mark.asyncio
async def test_sweep_onprem_wins_lane_dupes():
    # same repo returned under an onprem topic AND a broader topic
    client = _Client({
        "llm-inference": [_item("dual/repo", 1200)],  # onprem lane
        "generative-ai": [_item("dual/repo", 1200)],  # broader lane
    })

    observations = await sweep_trending([], client, NOW)

    dual = [o for o in observations if o.repo == "dual/repo"]
    assert len(dual) == 1 and dual[0].lane == Lane.ONPREM


@pytest.mark.asyncio
async def test_sweep_missing_license_is_none():
    client = _Client({"llm-inference": [_item("no/license", 900, spdx=None)]})

    observations = await sweep_trending([], client, NOW)

    assert observations[0].license is None


@pytest.mark.asyncio
async def test_sweep_one_failing_query_does_not_crash():
    client = _Client({"llm-inference": [_item("acme/rocket", 1500)]},
                     fail_substr="generative-ai")

    observations = await sweep_trending([], client, NOW)  # broader query raises

    assert any(o.repo == "acme/rocket" for o in observations)  # onprem still returned


@pytest.mark.asyncio
async def test_sweep_rising_shape_respects_lane_budget():
    from radar.discovery.trending_sweep import ONPREM_TOPICS, RISING_LANE_CAP

    first_topic = ONPREM_TOPICS[0]
    many = [_item(f"onprem/repo{i}", 1000 + i) for i in range(RISING_LANE_CAP + 5)]
    # _Client matches by topic substring only (not query shape), so without
    # failing the born query it would also match first_topic and pick up the
    # leftover items the rising shape skipped — isolate the rising shape here.
    client = _Client({first_topic: many}, fail_substr="created:")

    observations = await sweep_trending([], client, NOW)

    onprem = [o for o in observations if o.lane == Lane.ONPREM]
    assert len(onprem) == RISING_LANE_CAP  # rising budget bounds it; never more


class _ShapeClient:
    """Returns the born list when the query is the born shape (has 'created:'),
    the rising list otherwise — for every topic."""

    def __init__(self, rising: list[dict], born: list[dict]):
        self._rising = rising
        self._born = born

    async def get(self, url, **kwargs):
        query = kwargs.get("params", {}).get("q", "")
        return _Resp(self._born if "created:" in query else self._rising)


@pytest.mark.asyncio
async def test_sweep_born_shape_not_starved_by_full_rising():
    from radar.discovery.trending_sweep import RISING_LANE_CAP

    rising = [_item(f"rising/repo{i}", 1000 + i) for i in range(RISING_LANE_CAP + 5)]
    born = [_item("fresh/newcomer", 120, created="2026-07-01T00:00:00Z")]
    client = _ShapeClient(rising, born)

    observations = await sweep_trending([], client, NOW)

    # _ShapeClient serves every topic identically, so the broader lane's rising
    # query also matches "rising" and mops up the leftover items the onprem
    # lane's rising shape skipped — scope to the onprem lane being verified.
    onprem = [o for o in observations if o.lane == Lane.ONPREM]
    repos = {o.repo for o in onprem}
    assert "fresh/newcomer" in repos  # born signal survives a full rising page
    assert len([o for o in onprem if o.repo.startswith("rising/")]) == RISING_LANE_CAP
