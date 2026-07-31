from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from radar.intelligence.contracts import (
    EvidenceStrength,
    ModelCategory,
    ProductFamily,
    Publisher,
)
from radar.intelligence.database import Database
from radar.intelligence.jobs import JobKind
from radar.intelligence.pipeline import IntelligenceJobRunner
from radar.intelligence.repositories import SqlAlchemyIntelligenceRepository
from radar.intelligence.sources.base import DiscoveryCandidate, SourceRecord


OFFICIAL_TIME = datetime(2026, 7, 30, 8, 5, tzinfo=UTC)
DISCOVERY_TIME = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)


class MajorReleaseSource:
    id = "trusted-model-registry"

    async def discover(self, since: datetime) -> list[DiscoveryCandidate]:
        assert since <= OFFICIAL_TIME
        record = SourceRecord.from_bytes(
            source_id=self.id,
            url="https://huggingface.co/api/models/moonshotai/Kimi-K3",
            body=b'{"id":"moonshotai/Kimi-K3","lastModified":"2026-07-30T08:05:00Z"}',
            retrieved_at=DISCOVERY_TIME,
            strength=EvidenceStrength.TRUSTED_REGISTRY,
        )
        return [
            DiscoveryCandidate(
                source_record=record,
                external_id="moonshotai/Kimi-K3",
                publisher_hint="publisher:moonshot-ai",
                release_name="Kimi K3",
                category_hint=ModelCategory.MULTIMODAL,
                artifact_urls=["https://huggingface.co/moonshotai/Kimi-K3"],
                claims={
                    "repo_id": "moonshotai/Kimi-K3",
                    "release_date": OFFICIAL_TIME.isoformat(),
                },
            )
        ]

    async def fetch(self, url: str) -> SourceRecord:
        raise NotImplementedError


@pytest.mark.asyncio
async def test_official_release_is_detected_within_two_hours(tmp_path) -> None:
    (tmp_path / "data").mkdir()
    database = Database(f"sqlite:///{tmp_path / 'data' / 'intelligence.db'}")
    database.create_schema()
    repository = SqlAlchemyIntelligenceRepository(database)
    repository.upsert_publisher(
        Publisher(
            id="publisher:moonshot-ai",
            name="Moonshot AI",
            official_domains=["moonshot.ai"],
            official_accounts=["moonshotai"],
        )
    )
    repository.upsert_family(
        ProductFamily(
            id="family:moonshot-ai:kimi",
            publisher_id="publisher:moonshot-ai",
            name="Kimi",
        )
    )
    system = IntelligenceJobRunner(
        root=tmp_path,
        repository=repository,
        adapters=[MajorReleaseSource()],
        clock=lambda: DISCOVERY_TIME,
    )

    await system.run(JobKind.DISCOVERY, "job:slo")

    release = repository.get_release_required("release:moonshot-ai:kimi:k3")
    assert release.lifecycle.value == "detected"
    assert release.first_observed_at - OFFICIAL_TIME <= timedelta(hours=2)
    evidence = repository.get_evidence(
        repository.list_events(public_only=True)[0].evidence_ids[0]
    )
    assert evidence is not None
    assert evidence.strength in {
        EvidenceStrength.OFFICIAL_ARTIFACT,
        EvidenceStrength.OFFICIAL_REPOSITORY,
        EvidenceStrength.TRUSTED_REGISTRY,
    }
