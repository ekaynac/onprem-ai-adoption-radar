from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from radar.intelligence.contracts import (
    EvidenceStrength,
    LifecycleState,
    ModelCategory,
    ProductFamily,
    Publisher,
    ReleaseLane,
)
from radar.intelligence.database import Database
from radar.intelligence.jobs import JobKind
from radar.intelligence.migration import import_legacy_state
from radar.intelligence.pipeline import IntelligenceJobRunner
from radar.intelligence.repositories import SqlAlchemyIntelligenceRepository
from radar.intelligence.sources.base import DiscoveryCandidate, SourceRecord

from .test_migration import seed_legacy_root


NOW = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)


class FixtureAdapter:
    id = "fixture"

    async def discover(self, since: datetime) -> list[DiscoveryCandidate]:
        assert since == NOW - timedelta(days=3650)
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

    async def enrich(self, repo_id: str):
        assert repo_id == "moonshotai/Kimi-K3"
        record = SourceRecord.from_bytes(
            source_id=self.id,
            url="https://huggingface.co/api/models/moonshotai/Kimi-K3",
            body=b'{"library_name":"transformers","params":1000000000000}',
            retrieved_at=NOW,
            strength=EvidenceStrength.TRUSTED_REGISTRY,
            content_type="application/json",
        )
        return SimpleNamespace(
            records=[SimpleNamespace(source_record=record)],
            claims={
                "library_name": "transformers",
                "params_total": 1_000_000_000_000,
            },
            artifact_urls=[],
        )


class ProvisionalPublisherAdapter:
    id = "fixture-provisional"

    async def discover(self, since: datetime) -> list[DiscoveryCandidate]:
        del since
        record = SourceRecord.from_bytes(
            source_id=self.id,
            url="https://huggingface.co/acme/Acme-8B",
            body=b'{"id":"acme/Acme-8B"}',
            retrieved_at=NOW,
            strength=EvidenceStrength.TRUSTED_REGISTRY,
        )
        return [
            DiscoveryCandidate(
                source_record=record,
                external_id="acme/Acme-8B",
                publisher_hint="provisional:acme",
                release_name="Acme 8B",
                artifact_urls=["https://huggingface.co/acme/Acme-8B"],
                claims={"license": "apache-2.0"},
            )
        ]

    async def fetch(self, url: str) -> SourceRecord:
        raise NotImplementedError


class WatermarkAdapter:
    id = "fixture-watermark"

    def __init__(self) -> None:
        self.since_values: list[datetime] = []

    async def discover(self, since: datetime) -> list[DiscoveryCandidate]:
        self.since_values.append(since)
        return []

    async def fetch(self, url: str) -> SourceRecord:
        raise NotImplementedError


class PriorityFixtureAdapter:
    id = "fixture-priority"

    def __init__(self) -> None:
        self.enriched: list[str] = []

    async def discover(self, since: datetime) -> list[DiscoveryCandidate]:
        del since
        rows = []
        for repo_id, observed_at in (
            ("moonshotai/Historical-Model", NOW - timedelta(days=30)),
            ("moonshotai/Kimi-K3", NOW - timedelta(minutes=5)),
        ):
            record = SourceRecord.from_bytes(
                source_id=self.id,
                url=f"https://huggingface.co/api/models/{repo_id}",
                body=f'{{"id":"{repo_id}"}}'.encode(),
                retrieved_at=observed_at,
                strength=EvidenceStrength.TRUSTED_REGISTRY,
            )
            rows.append(
                DiscoveryCandidate(
                    source_record=record,
                    external_id=repo_id,
                    publisher_hint="publisher:moonshot-ai",
                    release_name=repo_id.split("/", 1)[1],
                    artifact_urls=[
                        f"https://huggingface.co/{repo_id}/resolve/main/model.safetensors"
                    ],
                    claims={
                        "repo_id": repo_id,
                        "license": "modified-mit",
                    },
                )
            )
        return rows

    async def fetch(self, url: str) -> SourceRecord:
        raise NotImplementedError

    async def enrich(self, repo_id: str):
        self.enriched.append(repo_id)
        record = SourceRecord.from_bytes(
            source_id=self.id,
            url=f"https://huggingface.co/api/models/{repo_id}",
            body=b'{"library_name":"transformers"}',
            retrieved_at=NOW,
            strength=EvidenceStrength.TRUSTED_REGISTRY,
        )
        return SimpleNamespace(
            records=[SimpleNamespace(source_record=record)],
            claims={"library_name": "transformers"},
            artifact_urls=[],
        )


class MigratedFixtureEnricher:
    id = "fixture-migrated"

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def enrich(self, repo_id: str):
        self.seen.append(repo_id)
        record = SourceRecord.from_bytes(
            source_id=self.id,
            url=f"https://huggingface.co/api/models/{repo_id}",
            body=b'{"library_name":"transformers"}',
            retrieved_at=NOW,
            strength=EvidenceStrength.TRUSTED_REGISTRY,
            content_type="application/json",
        )
        return SimpleNamespace(
            records=[SimpleNamespace(source_record=record)],
            claims={"library_name": "transformers"},
            artifact_urls=[f"https://huggingface.co/{repo_id}"],
        )


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
        "hf_repo",
        "license",
    }
    assert "repo_id" not in {
        claim.predicate for claim in repo.list_claims_for_subject(release.id)
    }
    events = repo.list_events(public_only=True)
    assert [event.type for event in events] == ["release.detected"]
    assert events[0].evidence_ids
    assert (tmp_path / "data" / "intelligence" / "events.jsonl").exists()
    assert list((tmp_path / "data" / "intelligence" / "snapshots").iterdir())


@pytest.mark.asyncio
async def test_enrichment_creates_documented_compatibility_and_can_qualify(
    tmp_path,
) -> None:
    repo = repository(tmp_path)
    runner = IntelligenceJobRunner(
        root=tmp_path,
        repository=repo,
        adapters=[FixtureAdapter()],
        clock=lambda: NOW,
    )

    await runner.run(JobKind.DISCOVERY, "job:discover")
    await runner.run(JobKind.VERIFY_NEW, "job:verify-new")
    await runner.run(JobKind.ENRICHMENT, "job:enrich")
    result = await runner.run(JobKind.QUALIFICATION, "job:qualify")

    release = repo.list_all_releases()[0]
    compatibility = repo.list_compatibility(release.id)
    assert result.updated == 1
    assert compatibility[0].platform_id == "platform:library:transformers"
    assert release.id == compatibility[0].release_id
    assert repo.get_release_required(release.id).lifecycle.value == "qualified"


@pytest.mark.asyncio
async def test_migrated_hf_repo_enriches_and_qualifies(tmp_path) -> None:
    seed_legacy_root(tmp_path)
    database = Database(f"sqlite:///{tmp_path / 'data' / 'intelligence.db'}")
    database.create_schema()
    repo = SqlAlchemyIntelligenceRepository(database)
    import_legacy_state(tmp_path, repo)
    adapter = MigratedFixtureEnricher()
    runner = IntelligenceJobRunner(
        root=tmp_path,
        repository=repo,
        adapters=[adapter],
        clock=lambda: NOW,
    )

    enriched = await runner.run(JobKind.ENRICHMENT, "job:enrich:migrated")
    qualified = await runner.run(JobKind.QUALIFICATION, "job:qualify:migrated")

    assert adapter.seen == ["acme/Sample-8B"]
    assert enriched.updated == 1
    assert qualified.updated == 1
    assert repo.get_release_required(
        "release:legacy:sample-8b"
    ).lifecycle.value == "qualified"


def test_identical_content_at_a_new_time_is_a_new_observation(tmp_path) -> None:
    repo = repository(tmp_path)
    runner = IntelligenceJobRunner(root=tmp_path, repository=repo)
    first = SourceRecord.from_bytes(
        source_id="fixture",
        url="https://example.test/model",
        body=b"same",
        retrieved_at=NOW,
        strength=EvidenceStrength.TRUSTED_REGISTRY,
    )
    second = first.model_copy(update={"retrieved_at": NOW + timedelta(hours=2)})

    first_evidence = runner._persist_source_record(first)
    second_evidence = runner._persist_source_record(second)

    assert first_evidence.id != second_evidence.id
    assert repo.get_evidence(first_evidence.id) == first_evidence
    assert repo.get_evidence(second_evidence.id) == second_evidence


@pytest.mark.asyncio
async def test_trusted_registry_can_add_a_provisional_publisher(tmp_path) -> None:
    repo = repository(tmp_path)
    runner = IntelligenceJobRunner(
        root=tmp_path,
        repository=repo,
        adapters=[ProvisionalPublisherAdapter()],
        clock=lambda: NOW,
    )

    result = await runner.run(JobKind.DISCOVERY, "job:provisional")

    assert result.created == 1
    assert "publisher:provisional:acme" in {
        publisher.id for publisher in repo.list_publishers()
    }
    assert any(
        release.publisher_id == "publisher:provisional:acme"
        for release in repo.list_all_releases()
    )
    assert repo.list_all_releases()[0].lane is ReleaseLane.ADJACENT


@pytest.mark.asyncio
async def test_discovery_resumes_from_last_success_with_overlap(tmp_path) -> None:
    repo = repository(tmp_path)
    adapter = WatermarkAdapter()
    runner = IntelligenceJobRunner(
        root=tmp_path,
        repository=repo,
        adapters=[adapter],
        clock=lambda: NOW,
    )

    await runner.run(JobKind.DISCOVERY, "job:first")
    later = NOW + timedelta(hours=6)
    runner.clock = lambda: later
    await runner.run(JobKind.DISCOVERY, "job:second")

    assert adapter.since_values == [
        NOW - timedelta(days=3650),
        NOW - timedelta(minutes=15),
    ]


@pytest.mark.asyncio
async def test_verify_new_prioritizes_recent_releases_and_reports_backlog(
    tmp_path,
) -> None:
    repo = repository(tmp_path)
    adapter = PriorityFixtureAdapter()
    runner = IntelligenceJobRunner(
        root=tmp_path,
        repository=repo,
        adapters=[adapter],
        clock=lambda: NOW,
        verification_batch_size=1,
    )
    await runner.run(JobKind.DISCOVERY, "job:discover-priority")

    result = await runner.run(JobKind.VERIFY_NEW, "job:verify-priority")

    releases = {release.name: release for release in repo.list_all_releases()}
    assert releases["Kimi-K3"].lifecycle is LifecycleState.VERIFIED
    assert releases["Historical-Model"].lifecycle is LifecycleState.DETECTED
    assert result.processed == 1
    assert result.remaining == 1


@pytest.mark.asyncio
async def test_enrichment_is_bounded_and_prioritizes_recent_releases(
    tmp_path,
) -> None:
    repo = repository(tmp_path)
    adapter = PriorityFixtureAdapter()
    runner = IntelligenceJobRunner(
        root=tmp_path,
        repository=repo,
        adapters=[adapter],
        clock=lambda: NOW,
        enrichment_batch_size=1,
    )
    await runner.run(JobKind.DISCOVERY, "job:discover-enrichment")
    await runner.run(JobKind.VERIFY_NEW, "job:verify-enrichment")

    result = await runner.run(JobKind.ENRICHMENT, "job:enrich-priority")

    assert adapter.enriched == ["moonshotai/Kimi-K3"]
    assert result.processed == 1
    assert result.remaining == 1
