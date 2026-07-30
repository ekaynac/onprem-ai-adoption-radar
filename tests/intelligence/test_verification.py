from __future__ import annotations

from radar.intelligence.contracts import (
    Claim,
    ClaimState,
    EvidenceObservation,
    EvidenceStrength,
    LifecycleState,
)
from radar.intelligence.verification import VerificationService

from .lifecycle_helpers import NOW, RELEASE_ID, lifecycle_repository


def seed_claim(repository, claim_id: str, predicate: str, value, suffix: str) -> None:
    evidence = EvidenceObservation(
        id=f"evidence:{suffix}",
        source_url=f"https://moonshot.ai/{suffix}",
        strength=EvidenceStrength.OFFICIAL_DOCUMENTATION,
        retrieved_at=NOW,
        checksum=f"sha256:{suffix}",
        extractor_version="test-v1",
    )
    repository.append_evidence(evidence)
    repository.append_claim(
        Claim(
            id=claim_id,
            subject_id=RELEASE_ID,
            predicate=predicate,
            value=value,
            state=ClaimState.CANDIDATE,
            observed_at=NOW,
            evidence_ids=[evidence.id],
        )
    )


def test_official_conflict_opens_review_and_blocks_verification(tmp_path) -> None:
    repository = lifecycle_repository(tmp_path)
    seed_claim(repository, "claim:license:one", "license", "mit", "one")
    seed_claim(repository, "claim:license:two", "license", "proprietary", "two")
    seed_claim(
        repository,
        "claim:artifact",
        "hf_repo",
        "moonshotai/Kimi-K3",
        "artifact",
    )

    result = VerificationService(repository).verify_release(RELEASE_ID, NOW)

    assert result.verified is False
    assert result.review_exception is not None
    assert result.review_exception.code == "conflicting_authoritative_claims"
    release = repository.get_release(RELEASE_ID)
    assert release is not None
    assert release.lifecycle is LifecycleState.DETECTED


def test_complete_official_claims_advance_release_to_verified(tmp_path) -> None:
    repository = lifecycle_repository(tmp_path)
    seed_claim(repository, "claim:license", "license", "mit", "license")
    seed_claim(
        repository,
        "claim:artifact",
        "hf_repo",
        "moonshotai/Kimi-K3",
        "artifact",
    )

    result = VerificationService(repository).verify_release(RELEASE_ID, NOW)

    assert result.verified is True
    assert result.missing_predicates == ()
    assert set(result.verified_claim_ids) == {"claim:license", "claim:artifact"}
    release = repository.get_release(RELEASE_ID)
    assert release is not None
    assert release.lifecycle is LifecycleState.VERIFIED
