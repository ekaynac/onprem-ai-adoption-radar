from __future__ import annotations

from datetime import timedelta

from radar.intelligence.services.container import build_services

from .lifecycle_helpers import NOW, RELEASE_ID, lifecycle_repository
from .test_recommendations import seed_recommendable_release


def test_release_stream_exposes_status_freshness_and_citations(tmp_path) -> None:
    repository = lifecycle_repository(tmp_path)
    seed_recommendable_release(repository)
    services = build_services(repository)

    result = services.releases.list_changes(
        since=NOW - timedelta(hours=2),
        limit=20,
        now=NOW,
    )

    item = next(
        row for row in result.items if row.release_id == RELEASE_ID
    )
    assert item.lifecycle == "detected"
    assert item.freshness == "fresh"
    assert item.citations[0].url.startswith("https://")
    assert item.confidence > 0


def test_release_get_uses_keyed_release_lookup(tmp_path, monkeypatch) -> None:
    repository = lifecycle_repository(tmp_path)
    seed_recommendable_release(repository)
    services = build_services(repository)

    def fail_scan():
        raise AssertionError("single-release lookup must not scan the catalog")

    monkeypatch.setattr(repository, "list_all_releases", fail_scan)

    item = services.releases.get(RELEASE_ID, now=NOW)

    assert item.release_id == RELEASE_ID
