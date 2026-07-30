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
from radar.intelligence.identity import IdentityResolver, normalize_identity
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
        aliases=["Kimi"],
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
    *,
    strength: EvidenceStrength = EvidenceStrength.TRUSTED_REGISTRY,
) -> DiscoveryCandidate:
    record = SourceRecord.from_bytes(
        source_id="test",
        url=f"https://example.com/{external_id}",
        body=external_id.encode(),
        retrieved_at=NOW,
        strength=strength,
    )
    return DiscoveryCandidate(
        source_record=record,
        external_id=external_id,
        publisher_hint=publisher_hint,
        release_name=name,
    )


def test_normalization_is_unicode_and_punctuation_stable() -> None:
    assert normalize_identity("  Kimi—K3  ") == "kimi-k3"


def test_exact_publisher_and_release_aliases_resolve(tmp_path) -> None:
    resolver = IdentityResolver(make_repository(tmp_path))

    by_account = resolver.resolve(
        candidate("moonshotai/Kimi-K3", "moonshotai", "Kimi-K3")
    )
    by_domain = resolver.resolve(
        candidate(
            "https://moonshot.ai/blog/kimi-k3",
            "moonshot.ai",
            "Kimi K3 released",
        )
    )

    assert by_account.release_id == "release:moonshot-ai:kimi:k3"
    assert by_domain.release_id == "release:moonshot-ai:kimi:k3"
    assert by_account.confidence == 1.0


def test_unknown_publisher_opens_review_instead_of_guessing(tmp_path) -> None:
    resolver = IdentityResolver(make_repository(tmp_path))

    result = resolver.resolve(candidate("acme/K3", "unknown", "K3"))

    assert result.release_id is None
    assert result.review_code == "ambiguous_identity"


def test_trusted_candidate_gets_deterministic_new_release_identity(
    tmp_path,
) -> None:
    resolver = IdentityResolver(make_repository(tmp_path))

    result = resolver.resolve(
        candidate("moonshotai/Kimi-K4", "moonshotai", "Kimi K4")
    )

    assert result.release_id == "release:moonshot-ai:kimi:k4"
    assert result.family_id == "family:moonshot-ai:kimi"
    assert result.is_new_release is True
