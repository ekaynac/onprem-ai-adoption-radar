from __future__ import annotations

from radar.intelligence.contracts import (
    ClaimState,
    CompatibilityAssertion,
    EvidenceLevel,
    EvidenceObservation,
    EvidenceStrength,
    SupportStatus,
)
from radar.intelligence.platforms import PlatformIntelligenceService

from .lifecycle_helpers import NOW, RELEASE_ID, lifecycle_repository


def test_removed_platform_doc_marks_claim_stale_not_no(tmp_path) -> None:
    repository = lifecycle_repository(tmp_path)
    evidence = EvidenceObservation(
        id="evidence:vllm:kimi",
        source_url="https://docs.vllm.ai/models/kimi",
        strength=EvidenceStrength.OFFICIAL_DOCUMENTATION,
        retrieved_at=NOW,
        checksum="sha256:vllm",
        extractor_version="test-v1",
    )
    repository.append_evidence(evidence)
    service = PlatformIntelligenceService(repository)
    service.upsert_assertion(
        CompatibilityAssertion(
            id="compat:vllm:kimi",
            release_id=RELEASE_ID,
            platform_id="platform:vllm",
            platform_version="0.10.0",
            feature="model_loading",
            support=SupportStatus.YES,
            evidence_level=EvidenceLevel.DOCUMENTED,
            evidence_ids=[evidence.id],
            hardware_scope=["nvidia"],
        ),
        now=NOW,
    )

    service.mark_source_unavailable("evidence:vllm:kimi", NOW)

    assertion = repository.get_compatibility("compat:vllm:kimi")
    assert assertion is not None
    assert assertion.support is SupportStatus.YES
    claim = repository.get_claim(assertion.id)
    assert claim is not None
    assert claim.state is ClaimState.STALE


def test_exact_tested_version_outranks_documented_range(tmp_path) -> None:
    repository = lifecycle_repository(tmp_path)
    service = PlatformIntelligenceService(repository)
    for suffix, version, level in (
        ("range", ">=0.9,<0.11", EvidenceLevel.DOCUMENTED),
        ("exact", "0.10.0", EvidenceLevel.TESTED),
    ):
        evidence = EvidenceObservation(
            id=f"evidence:{suffix}",
            source_url=f"https://example.com/{suffix}",
            strength=EvidenceStrength.OFFICIAL_DOCUMENTATION,
            retrieved_at=NOW,
            checksum=f"sha256:{suffix}",
            extractor_version="test-v1",
        )
        repository.append_evidence(evidence)
        service.upsert_assertion(
            CompatibilityAssertion(
                id=f"compat:{suffix}",
                release_id=RELEASE_ID,
                platform_id="platform:vllm",
                platform_version=version,
                feature="model_loading",
                support=SupportStatus.YES,
                evidence_level=level,
                evidence_ids=[evidence.id],
            ),
            now=NOW,
        )

    best = service.best_assertion(
        RELEASE_ID,
        "platform:vllm",
        "model_loading",
    )

    assert best is not None
    assert best.id == "compat:exact"
