"""Category dispatch and lifecycle-aware qualification."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from radar.intelligence.contracts import (
    Claim,
    ClaimState,
    CompatibilityAssertion,
    LifecycleState,
    ModelCategory,
    Qualification,
    Release,
)
from radar.intelligence.lifecycle import LifecycleService
from radar.intelligence.qualifiers import (
    AudioQualifier,
    DocumentQualifier,
    EmbeddingQualifier,
    LanguageQualifier,
    MediaQualifier,
)


class CategoryQualifier(Protocol):
    required_predicates: tuple[str, ...]
    fit_metrics: tuple[str, ...]
    risk_checks: tuple[str, ...]

    def qualify(
        self,
        release: Release,
        claims: dict[str, Claim],
        compatibility: list[CompatibilityAssertion],
    ) -> Qualification: ...


QUALIFIER_FACTORIES = {
    ModelCategory.TEXT_REASONING: LanguageQualifier,
    ModelCategory.MULTIMODAL: LanguageQualifier,
    ModelCategory.EMBEDDING_RERANKING: EmbeddingQualifier,
    ModelCategory.SPEECH_AUDIO: AudioQualifier,
    ModelCategory.IMAGE_VIDEO: MediaQualifier,
    ModelCategory.VISION_DOCUMENT: DocumentQualifier,
}


def build_qualifier(category: ModelCategory) -> CategoryQualifier:
    return QUALIFIER_FACTORIES[category]()


class QualificationRepository(Protocol):
    def get_release_required(self, release_id: str) -> Release: ...

    def list_claims_for_subject(self, subject_id: str) -> list[Claim]: ...

    def list_compatibility(
        self,
        release_id: str,
    ) -> list[CompatibilityAssertion]: ...

    def get_claim(self, claim_id: str) -> Claim | None: ...

    def save_qualification(
        self,
        qualification: Qualification,
        now: datetime,
    ) -> None: ...

    def append_lifecycle_transition(self, transition) -> None: ...

    def set_release_lifecycle(
        self,
        release_id: str,
        lifecycle: LifecycleState,
    ) -> None: ...


class QualificationService:
    def __init__(self, repository: QualificationRepository):
        self.repository = repository

    def qualify(
        self,
        release_id: str,
        now: datetime,
    ) -> Qualification:
        release = self.repository.get_release_required(release_id)
        claims = _current_verified_claims(
            self.repository.list_claims_for_subject(release_id)
        )
        compatibility = [
            assertion
            for assertion in self.repository.list_compatibility(release_id)
            if (
                (backing := self.repository.get_claim(assertion.id))
                is not None
                and backing.state is not ClaimState.STALE
            )
        ]
        result = build_qualifier(release.category).qualify(
            release,
            claims,
            compatibility,
        )
        if release.lifecycle is not LifecycleState.VERIFIED:
            result = result.model_copy(
                update={
                    "qualified": False,
                    "reasons": [
                        *result.reasons,
                        "Release must be Verified before qualification",
                    ],
                }
            )
        self.repository.save_qualification(result, now)
        if result.qualified:
            LifecycleService(self.repository).transition(
                release_id,
                LifecycleState.QUALIFIED,
                reason="Category and platform qualification satisfied",
                evidence_ids=result.evidence_ids,
                now=now,
            )
        return result


def _current_verified_claims(claims: list[Claim]) -> dict[str, Claim]:
    selected: dict[str, Claim] = {}
    for claim in claims:
        if claim.state is not ClaimState.VERIFIED:
            continue
        current = selected.get(claim.predicate)
        if current is None or (claim.observed_at, claim.id) > (
            current.observed_at,
            current.id,
        ):
            selected[claim.predicate] = claim
    return selected
