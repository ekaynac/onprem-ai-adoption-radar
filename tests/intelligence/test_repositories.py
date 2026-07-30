from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from radar.intelligence.contracts import (
    Claim,
    ClaimState,
    EvidenceObservation,
    EvidenceStrength,
)
from radar.intelligence.database import Database
from radar.intelligence.repositories import (
    RepositoryConflict,
    SqlAlchemyIntelligenceRepository,
)


NOW = datetime(2026, 7, 30, tzinfo=UTC)


def make_evidence(
    evidence_id: str = "evidence:one",
    checksum: str = "sha256:one",
) -> EvidenceObservation:
    return EvidenceObservation(
        id=evidence_id,
        source_url="https://example.com/config.json",
        strength=EvidenceStrength.OFFICIAL_ARTIFACT,
        retrieved_at=NOW,
        checksum=checksum,
        extractor_version="test-v1",
    )


def make_repository(url: str) -> SqlAlchemyIntelligenceRepository:
    database = Database(url)
    database.create_schema()
    return SqlAlchemyIntelligenceRepository(database)


def test_evidence_is_append_only_and_idempotent(tmp_path) -> None:
    repo = make_repository(f"sqlite:///{tmp_path / 'intelligence.db'}")
    evidence = make_evidence()

    repo.append_evidence(evidence)
    repo.append_evidence(evidence)

    assert repo.get_evidence("evidence:one") == evidence
    assert repo.count_evidence() == 1


def test_changed_payload_under_existing_evidence_id_is_rejected(tmp_path) -> None:
    repo = make_repository(f"sqlite:///{tmp_path / 'intelligence.db'}")
    repo.append_evidence(make_evidence())

    with pytest.raises(RepositoryConflict, match="Evidence id changed"):
        repo.append_evidence(make_evidence(checksum="sha256:changed"))


def test_verified_claim_round_trips_with_its_evidence(tmp_path) -> None:
    repo = make_repository(f"sqlite:///{tmp_path / 'intelligence.db'}")
    evidence = make_evidence()
    claim = Claim(
        id="claim:kimi-k3:context",
        subject_id="release:kimi-k3",
        predicate="context_tokens",
        value=1_048_576,
        state=ClaimState.VERIFIED,
        observed_at=NOW,
        evidence_ids=[evidence.id],
        unit="tokens",
    )

    repo.append_evidence(evidence)
    repo.append_claim(claim)

    assert repo.get_claim(claim.id) == claim


def test_sqlite_enables_foreign_keys(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'intelligence.db'}")
    with database.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


@pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES_URL"),
    reason="TEST_POSTGRES_URL is not configured",
)
def test_postgres_implements_same_evidence_contract() -> None:
    repo = make_repository(os.environ["TEST_POSTGRES_URL"])
    evidence = make_evidence("evidence:postgres")

    repo.append_evidence(evidence)

    assert repo.get_evidence(evidence.id) == evidence
