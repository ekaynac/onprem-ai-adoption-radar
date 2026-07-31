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


NOW = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)


class FixtureAdapter:
    id = "fixture"

    async def discover(self, since: datetime) -> list[DiscoveryCandidate]:
        assert since == NOW - timedelta(hours=2)
        record = SourceRecord.from_bytes(
            source_id=self.id,
            url="https://huggingface.co/api/models/moonshotai/Kimi-K3",
            body=b'{"id":"moonshotai/Kimi-K3"}',
            retrieved_at=NOW,
            strength=EvidenceStrength.TRUSTED_REGISTRY,
            content_type="application/json",
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
                    "license": "modified-mit",
                },
            )
        ]

    async def fetch(self, url: str) -> SourceRecord:
        raise NotImplementedError


def repository(tmp_path):
    (tmp_path / "data").mkdir()
    database = Database(f"sqlite:///{tmp_path / 'data' / 'intelligence.db'}")
    database.create_schema()
    repo = SqlAlchemyIntelligenceRepository(database)
    repo.upsert_publisher(
        Publisher(
            id="publisher:moonshot-ai",
            name="Moonshot AI",
            official_domains=["moonshot.ai"],
            official_accounts=["moonshotai"],
            aliases=["Moonshot"],
        )
    )
    repo.upsert_family(
        ProductFamily(
            id="family:moonshot-ai:kimi",
            publisher_id="publisher:moonshot-ai",
            name="Kimi",
            aliases=["Kimi"],
        )
    )
    return repo


@pytest.mark.asyncio
async def test_discovery_job_creates_cited_release_event_and_snapshot(tmp_path) -> None:
    repo = repository(tmp_path)
    runner = IntelligenceJobRunner(
        root=tmp_path,
        repository=repo,
        adapters=[FixtureAdapter()],
        clock=lambda: NOW,
    )

    result = await runner.run(JobKind.DISCOVERY, "job:test")

    assert result.discovered == 1
    assert result.created == 1
    release = repo.list_all_releases()[0]
    assert release.name == "Kimi K3"
    assert release.lifecycle.value == "detected"
    assert {claim.predicate for claim in repo.list_claims_for_subject(release.id)} >= {
        "artifact_url",
        "license",
        "repo_id",
    }
    events = repo.list_events(public_only=True)
    assert [event.type for event in events] == ["release.detected"]
    assert events[0].evidence_ids
    assert (tmp_path / "data" / "intelligence" / "events.jsonl").exists()
    assert list((tmp_path / "data" / "intelligence" / "snapshots").iterdir())
