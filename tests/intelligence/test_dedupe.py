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
from radar.intelligence.dedupe import cluster_candidates
from radar.intelligence.identity import IdentityResolver
from radar.intelligence.repositories import SqlAlchemyIntelligenceRepository
from radar.intelligence.sources.base import DiscoveryCandidate, SourceRecord


NOW = datetime(2026, 7, 30, tzinfo=UTC)


def make_repository(tmp_path) -> SqlAlchemyIntelligenceRepository:
    database = Database(f"sqlite:///{tmp_path / 'intelligence.db'}")
    database.create_schema()
    repository = SqlAlchemyIntelligenceRepository(database)
    publisher = Publisher(
        id="publisher:moonshot-ai",
        name="Moonshot AI",
        official_domains=["moonshot.ai"],
        official_accounts=["moonshotai"],
        aliases=["MoonshotAI"],
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
            id="release:moonshot-ai:kimi:k3",
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


def candidate(
    external_id: str,
    publisher_hint: str,
    name: str,
) -> DiscoveryCandidate:
    return DiscoveryCandidate(
        source_record=SourceRecord.from_bytes(
            source_id="test",
            url=f"https://example.com/{external_id}",
            body=external_id.encode(),
            retrieved_at=NOW,
            strength=EvidenceStrength.TRUSTED_REGISTRY,
        ),
        external_id=external_id,
        publisher_hint=publisher_hint,
        release_name=name,
    )


def test_hf_github_and_blog_resolve_to_one_release(tmp_path) -> None:
    resolver = IdentityResolver(make_repository(tmp_path))
    candidates = [
        candidate("moonshotai/Kimi-K3", "moonshotai", "Kimi-K3"),
        candidate("MoonshotAI/Kimi-K3", "MoonshotAI", "Kimi K3"),
        candidate(
            "https://moonshot.ai/blog/kimi-k3",
            "moonshot.ai",
            "Kimi K3 released",
        ),
    ]

    clusters = cluster_candidates(candidates, resolver)

    assert len(clusters) == 1
    assert clusters[0].canonical_release_id == "release:moonshot-ai:kimi:k3"
    assert len(clusters[0].candidates) == 3


def test_conflicting_category_hints_stay_clustered_and_are_flagged(
    tmp_path,
) -> None:
    resolver = IdentityResolver(make_repository(tmp_path))
    first = candidate("moonshotai/Kimi-K3", "moonshotai", "Kimi-K3")
    second = candidate("MoonshotAI/Kimi-K3", "MoonshotAI", "Kimi K3")
    first = first.model_copy(
        update={"category_hint": ModelCategory.MULTIMODAL}
    )
    second = second.model_copy(
        update={"category_hint": ModelCategory.TEXT_REASONING}
    )

    clusters = cluster_candidates([first, second], resolver)

    assert len(clusters) == 1
    assert clusters[0].conflict_claims == ("category_hint",)
