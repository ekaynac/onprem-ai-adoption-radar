from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from radar.api.app import create_api_app
from radar.intelligence.contracts import (
    Claim,
    ClaimState,
    EvidenceObservation,
    EvidenceStrength,
    LifecycleState,
    ModelCategory,
    ProductFamily,
    Publisher,
    Qualification,
    Release,
    ReleaseLane,
)
from radar.intelligence.database import Database
from radar.intelligence.events import IntelligenceEvent
from radar.intelligence.repositories import SqlAlchemyIntelligenceRepository
from radar.intelligence.services.container import build_services
from radar.mcp_server.intelligence_queries import IntelligenceQueryService
from radar.reports.intelligence_feeds import (
    render_intelligence_atom,
    render_intelligence_json_feed,
    render_intelligence_rss,
)
from radar.web.intelligence_snapshot import build_public_snapshot


NOW = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
RELEASE_ID = "release:moonshot-ai:kimi:k3"


def parity_repository(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'intelligence.db'}")
    database.create_schema()
    repository = SqlAlchemyIntelligenceRepository(database)
    publisher = Publisher(
        id="publisher:moonshot-ai",
        name="Moonshot AI",
        official_domains=["moonshot.ai"],
        official_accounts=["moonshotai"],
    )
    family = ProductFamily(
        id="family:moonshot-ai:kimi",
        publisher_id=publisher.id,
        name="Kimi",
    )
    repository.upsert_publisher(publisher)
    repository.upsert_family(family)
    repository.upsert_release(
        Release(
            id=RELEASE_ID,
            family_id=family.id,
            publisher_id=publisher.id,
            name="Kimi K3",
            category=ModelCategory.MULTIMODAL,
            lane=ReleaseLane.DEPLOYABLE,
            lifecycle=LifecycleState.DETECTED,
            first_observed_at=NOW,
            discovery_evidence_strength=EvidenceStrength.TRUSTED_REGISTRY,
        )
    )
    evidence = EvidenceObservation(
        id="evidence:qualification",
        source_url="https://moonshot.ai/kimi-k3",
        strength=EvidenceStrength.OFFICIAL_DOCUMENTATION,
        retrieved_at=NOW,
        checksum="sha256:qualification",
        extractor_version="test-v1",
    )
    repository.append_evidence(evidence)
    for predicate, value in (
        ("repo_id", "moonshotai/Kimi-K3"),
        ("license", "modified-mit"),
    ):
        repository.append_claim(
            Claim(
                id=f"claim:{predicate}",
                subject_id=RELEASE_ID,
                predicate=predicate,
                value=value,
                state=ClaimState.VERIFIED,
                observed_at=NOW,
                evidence_ids=[evidence.id],
            )
        )
    repository.save_qualification(
        Qualification(
            release_id=RELEASE_ID,
            qualified=True,
            category=ModelCategory.MULTIMODAL,
            reasons=["Verified deployable artifact"],
            assumptions=[],
            evidence_ids=[evidence.id],
        ),
        NOW,
    )
    return repository


def test_api_mcp_feeds_and_snapshot_share_release_and_event_identity(tmp_path) -> None:
    repository = parity_repository(tmp_path)
    event = IntelligenceEvent.for_lifecycle(
        release_id=RELEASE_ID,
        from_state=None,
        to_state=LifecycleState.DETECTED,
        occurred_at=NOW,
        evidence_ids=["evidence:qualification"],
    )
    repository.append_event(event)
    services = build_services(repository)

    api = TestClient(
        create_api_app(
            tmp_path,
            services=services,
            repository=repository,
        )
    ).get("/api/v1/releases").json()
    mcp = IntelligenceQueryService(services, repository).list_releases(
        None,
        10,
        now=NOW,
    )
    snapshot = build_public_snapshot(services, NOW).model_dump(mode="json")
    atom = render_intelligence_atom([event], "https://radar.example")
    rss = render_intelligence_rss([event], "https://radar.example")
    json_feed = json.loads(
        render_intelligence_json_feed([event], "https://radar.example")
    )

    assert api["items"][0]["release_id"] == RELEASE_ID
    assert mcp[0]["id"] == RELEASE_ID
    assert snapshot["releases"][0]["release_id"] == RELEASE_ID
    assert snapshot["events"][0]["id"] == event.id
    assert event.id in atom and event.id in rss
    assert json_feed["items"][0]["id"] == event.id
    assert "workspace" not in json.dumps(snapshot).casefold()
