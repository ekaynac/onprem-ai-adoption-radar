from __future__ import annotations

from datetime import UTC, datetime

from radar.intelligence.contracts import (
    EvidenceStrength,
    LifecycleState,
    ModelCategory,
    ProductFamily,
    Publisher,
    Release,
    ReleaseLane,
)
from radar.intelligence.database import Database
from radar.intelligence.repositories import SqlAlchemyIntelligenceRepository


NOW = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
RELEASE_ID = "release:moonshot-ai:kimi:k3"


def lifecycle_repository(tmp_path) -> SqlAlchemyIntelligenceRepository:
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
    return repository
