from __future__ import annotations

from datetime import UTC, datetime

from intelligence.lifecycle_helpers import lifecycle_repository
from intelligence.test_recommendations import seed_recommendable_release
from radar.intelligence.services.container import build_services
from radar.mcp_server.intelligence_queries import IntelligenceQueryService


def test_list_releases_returns_compact_cited_rows(tmp_path) -> None:
    repository = lifecycle_repository(tmp_path)
    seed_recommendable_release(repository)
    service = IntelligenceQueryService(build_services(repository), repository)

    payload = service.list_releases(
        "2026-07-30T08:00:00Z",
        10,
        now=datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
    )

    assert payload
    assert set(payload[0]) <= {
        "id",
        "name",
        "category",
        "lane",
        "lifecycle",
        "age",
        "headline",
        "citation_count",
        "freshness",
        "review",
    }
    assert payload[0]["citation_count"] > 0
