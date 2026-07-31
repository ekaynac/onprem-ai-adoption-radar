"""Version-aware platform compatibility projections."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from radar.intelligence.contracts import (
    Claim,
    ClaimState,
    CompatibilityAssertion,
    EvidenceLevel,
)


_EVIDENCE_LEVEL_RANK = {
    EvidenceLevel.INFERRED: 1,
    EvidenceLevel.DOCUMENTED: 2,
    EvidenceLevel.TESTED: 3,
}


class PlatformRepository(Protocol):
    def upsert_compatibility(
        self,
        assertion: CompatibilityAssertion,
    ) -> bool: ...

    def append_claim(self, claim: Claim) -> None: ...

    def list_compatibility(
        self,
        release_id: str,
    ) -> list[CompatibilityAssertion]: ...

    def list_compatibility_for_evidence(
        self,
        evidence_id: str,
    ) -> list[CompatibilityAssertion]: ...

    def set_claim_state(self, claim_id: str, state: ClaimState) -> None: ...


class PlatformIntelligenceService:
    def __init__(self, repository: PlatformRepository):
        self.repository = repository

    def upsert_assertion(
        self,
        assertion: CompatibilityAssertion,
        *,
        now: datetime,
    ) -> bool:
        created = self.repository.upsert_compatibility(assertion)
        self.repository.append_claim(
            Claim(
                id=assertion.id,
                subject_id=assertion.release_id,
                predicate="platform_compatibility",
                value=assertion.model_dump(mode="json"),
                state=ClaimState.VERIFIED,
                observed_at=now,
                evidence_ids=assertion.evidence_ids,
            )
        )
        return created

    def mark_source_unavailable(
        self,
        evidence_id: str,
        now: datetime,
    ) -> None:
        del now
        for assertion in self.repository.list_compatibility_for_evidence(
            evidence_id
        ):
            self.repository.set_claim_state(assertion.id, ClaimState.STALE)

    def best_assertion(
        self,
        release_id: str,
        platform_id: str,
        feature: str,
    ) -> CompatibilityAssertion | None:
        matches = [
            assertion
            for assertion in self.repository.list_compatibility(release_id)
            if assertion.platform_id == platform_id
            and assertion.feature == feature
        ]
        if not matches:
            return None
        return max(
            matches,
            key=lambda assertion: (
                _is_exact_version(assertion.platform_version),
                _EVIDENCE_LEVEL_RANK[assertion.evidence_level],
                assertion.platform_version,
                assertion.id,
            ),
        )


def _is_exact_version(value: str) -> bool:
    return not any(character in value for character in "<>=*xX,")
