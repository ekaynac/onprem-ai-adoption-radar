from __future__ import annotations

import pytest

from radar.intelligence.contracts import (
    Claim,
    ClaimState,
    CompatibilityAssertion,
    EvidenceLevel,
    EvidenceObservation,
    EvidenceStrength,
    LifecycleState,
    ModelCategory,
    SupportStatus,
)
from radar.intelligence.platforms import PlatformIntelligenceService
from radar.intelligence.qualification import (
    QualificationService,
    build_qualifier,
)
from radar.intelligence.qualifiers.audio import AudioQualifier
from radar.intelligence.qualifiers.document import DocumentQualifier
from radar.intelligence.qualifiers.embedding import EmbeddingQualifier
from radar.intelligence.qualifiers.language import LanguageQualifier
from radar.intelligence.qualifiers.media import MediaQualifier

from .lifecycle_helpers import NOW, RELEASE_ID, lifecycle_repository


@pytest.mark.parametrize(
    ("category", "qualifier_type"),
    [
        (ModelCategory.TEXT_REASONING, LanguageQualifier),
        (ModelCategory.MULTIMODAL, LanguageQualifier),
        (ModelCategory.EMBEDDING_RERANKING, EmbeddingQualifier),
        (ModelCategory.SPEECH_AUDIO, AudioQualifier),
        (ModelCategory.IMAGE_VIDEO, MediaQualifier),
        (ModelCategory.VISION_DOCUMENT, DocumentQualifier),
    ],
)
def test_every_category_has_a_qualifier(category, qualifier_type) -> None:
    assert isinstance(build_qualifier(category), qualifier_type)


def test_verified_release_with_documented_platform_support_qualifies(
    tmp_path,
) -> None:
    repository = lifecycle_repository(tmp_path)
    repository.set_release_lifecycle(RELEASE_ID, LifecycleState.VERIFIED)
    evidence = EvidenceObservation(
        id="evidence:vllm:kimi",
        source_url="https://docs.vllm.ai/models/kimi",
        strength=EvidenceStrength.OFFICIAL_DOCUMENTATION,
        retrieved_at=NOW,
        checksum="sha256:vllm",
        extractor_version="test-v1",
    )
    repository.append_evidence(evidence)
    repository.append_claim(
        Claim(
            id="claim:params",
            subject_id=RELEASE_ID,
            predicate="params_total",
            value=1_000_000_000_000,
            state=ClaimState.VERIFIED,
            observed_at=NOW,
            evidence_ids=[evidence.id],
        )
    )
    PlatformIntelligenceService(repository).upsert_assertion(
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

    result = QualificationService(repository).qualify(RELEASE_ID, NOW)

    assert result.qualified is True
    assert repository.get_release(RELEASE_ID).lifecycle is LifecycleState.QUALIFIED
    assert any("memory" in reason.casefold() for reason in result.reasons)
