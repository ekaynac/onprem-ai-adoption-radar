from datetime import UTC, datetime

from radar.intelligence.contracts import LifecycleState
from radar.intelligence.events import IntelligenceEvent


def _seed_public_event(repository) -> IntelligenceEvent:
    event = IntelligenceEvent.for_lifecycle(
        release_id="release:kimi-k3",
        from_state=LifecycleState.DETECTED,
        to_state=LifecycleState.VERIFIED,
        occurred_at=datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
        evidence_ids=[],
    )
    repository.append_event(event)
    return event


def test_versioned_feed_routes_share_public_event_identity(
    api_client,
    api_repository,
) -> None:
    event = _seed_public_event(api_repository)

    atom = api_client.get("/api/v1/integrations/feed.atom")
    rss = api_client.get("/api/v1/integrations/feed.rss")
    json_feed = api_client.get("/api/v1/integrations/feed.json")

    assert atom.status_code == rss.status_code == json_feed.status_code == 200
    assert event.id in atom.text
    assert event.id in rss.text
    assert json_feed.json()["items"][0]["id"] == event.id


def test_public_snapshot_route_never_contains_workspace_data(api_client) -> None:
    response = api_client.get("/api/v1/integrations/public-snapshot")

    assert response.status_code == 200
    assert response.json()["schema_version"] == "1.0"
    assert "workspace" not in response.text.casefold()
