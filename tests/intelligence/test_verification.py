from __future__ import annotations

from datetime import timedelta

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
    claims = repository.list_claims_for_subject(RELEASE_ID)
    assert {claim.state for claim in claims} == {ClaimState.VERIFIED}


def test_new_observation_from_same_source_supersedes_old_value(tmp_path) -> None:
    repository = lifecycle_repository(tmp_path)
    seed_claim(
        repository,
        "claim:artifact",
        "hf_repo",
        "moonshotai/Kimi-K3",
        "artifact",
    )
    for suffix, value, observed_at in (
        ("old", "proprietary", NOW - timedelta(days=1)),
        ("new", "mit", NOW),
    ):
        evidence = EvidenceObservation(
            id=f"evidence:license:{suffix}",
            source_url="https://moonshot.ai/kimi-k3/license",
            strength=EvidenceStrength.OFFICIAL_DOCUMENTATION,
            retrieved_at=observed_at,
            checksum=f"sha256:{suffix}",
            extractor_version="test-v1",
        )
        repository.append_evidence(evidence)
        repository.append_claim(
            Claim(
                id=f"claim:license:{suffix}",
                subject_id=RELEASE_ID,
                predicate="license",
                value=value,
                state=ClaimState.CANDIDATE,
                observed_at=observed_at,
                evidence_ids=[evidence.id],
            )
        )

    result = VerificationService(repository).verify_release(RELEASE_ID, NOW)

    assert result.verified is True
    assert result.review_exception is None
    assert repository.get_claim("claim:license:new").state is ClaimState.VERIFIED


def test_nonrequired_conflict_does_not_block_release_verification(tmp_path) -> None:
    repository = lifecycle_repository(tmp_path)
    seed_claim(repository, "claim:license", "license", "mit", "license")
    seed_claim(
        repository,
        "claim:artifact",
        "hf_repo",
        "moonshotai/Kimi-K3",
        "artifact",
    )
    # A non-required (but non-volatile) fact in dispute: reviewable,
    # yet it must not block verification of the required set.
    seed_claim(
        repository, "claim:pipeline:one", "pipeline_tag", "text-generation", "one"
    )
    seed_claim(
        repository, "claim:pipeline:two", "pipeline_tag", "text2text", "two"
    )

    result = VerificationService(repository).verify_release(RELEASE_ID, NOW)

    assert result.verified is True
    assert result.review_exception is not None
    assert repository.get_release_required(
        RELEASE_ID
    ).lifecycle is LifecycleState.VERIFIED


def test_volatile_metric_drift_never_opens_a_conflict_review(tmp_path) -> None:
    """Production repro (2026-08-03..05 flood): repeated scans see different
    downloads/likes/last_modified/sha values from different source URLs —
    that is metric drift, not a dispute, and must not open a review."""
    repository = lifecycle_repository(tmp_path)
    for predicate in ("downloads", "likes", "last_modified", "sha"):
        seed_claim(
            repository,
            f"claim:{predicate}:one",
            predicate,
            f"{predicate}-value-1",
            f"{predicate}-one",
        )
        seed_claim(
            repository,
            f"claim:{predicate}:two",
            predicate,
            f"{predicate}-value-2",
            f"{predicate}-two",
        )
    # Required identity claims so verification can otherwise proceed.
    seed_claim(repository, "claim:license", "license", "mit", "license")
    seed_claim(
        repository, "claim:artifact", "hf_repo", "moonshotai/Kimi-K3", "artifact"
    )

    result = VerificationService(repository).verify_release(RELEASE_ID, NOW)

    assert result.review_exception is None


def test_mixed_conflict_review_lists_only_real_predicates(tmp_path) -> None:
    repository = lifecycle_repository(tmp_path)
    seed_claim(repository, "claim:downloads:one", "downloads", 10, "d-one")
    seed_claim(repository, "claim:downloads:two", "downloads", 999, "d-two")
    seed_claim(repository, "claim:license:one", "license", "mit", "one")
    seed_claim(repository, "claim:license:two", "license", "proprietary", "two")

    result = VerificationService(repository).verify_release(RELEASE_ID, NOW)

    assert result.review_exception is not None
    assert result.review_exception.message == (
        "Authoritative evidence conflicts for: license"
    )
