from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from radar.intelligence.contracts import (
    Claim,
    ClaimState,
    EvidenceObservation,
    EvidenceStrength,
    LifecycleState,
    ModelCategory,
    Release,
    ReleaseLane,
)


NOW = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)


def test_detected_release_requires_public_discovery_source() -> None:
    with pytest.raises(ValidationError, match="official or trusted"):
        Release(
            id="release:kimi-k3",
            family_id="family:kimi",
            publisher_id="publisher:moonshot-ai",
            name="Kimi K3",
            category=ModelCategory.MULTIMODAL,
            lane=ReleaseLane.DEPLOYABLE,
            lifecycle=LifecycleState.DETECTED,
            first_observed_at=NOW,
            discovery_evidence_strength=EvidenceStrength.COMMUNITY,
        )


def test_detected_release_accepts_trusted_registry_source() -> None:
    release = Release(
        id="release:kimi-k3",
        family_id="family:kimi",
        publisher_id="publisher:moonshot-ai",
        name="Kimi K3",
        category=ModelCategory.MULTIMODAL,
        lane=ReleaseLane.DEPLOYABLE,
        lifecycle=LifecycleState.DETECTED,
        first_observed_at=NOW,
        discovery_evidence_strength=EvidenceStrength.TRUSTED_REGISTRY,
    )

    assert release.lifecycle is LifecycleState.DETECTED


def test_verified_claim_requires_evidence_ids() -> None:
    with pytest.raises(ValidationError, match="evidence"):
        Claim(
            id="claim:kimi-k3:context",
            subject_id="release:kimi-k3",
            predicate="context_tokens",
            value=1_048_576,
            state=ClaimState.VERIFIED,
            observed_at=NOW,
            evidence_ids=[],
        )


def test_evidence_observation_is_immutable() -> None:
    evidence = EvidenceObservation(
        id="evidence:hf:kimi-k3:config",
        source_url="https://huggingface.co/moonshotai/Kimi-K3/raw/main/config.json",
        strength=EvidenceStrength.OFFICIAL_ARTIFACT,
        retrieved_at=NOW,
        checksum="sha256:abc",
        extractor_version="hf-config-v1",
    )

    with pytest.raises(ValidationError, match="frozen"):
        evidence.checksum = "sha256:changed"
