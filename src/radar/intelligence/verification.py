"""Deterministic evidence-based release verification."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from radar.intelligence.contracts import (
    Claim,
    ClaimState,
    EvidenceObservation,
    EvidenceStrength,
    LifecycleState,
    Release,
    ReleaseLane,
    ReviewException,
)
from radar.intelligence.lifecycle import LifecycleService


_STRENGTH_RANK = {
    EvidenceStrength.OFFICIAL_ARTIFACT: 100,
    EvidenceStrength.OFFICIAL_DOCUMENTATION: 95,
    EvidenceStrength.OFFICIAL_REPOSITORY: 95,
    EvidenceStrength.OFFICIAL_ANNOUNCEMENT: 90,
    EvidenceStrength.TRUSTED_REGISTRY: 80,
    EvidenceStrength.BENCHMARK_MAINTAINER: 70,
    EvidenceStrength.AGGREGATOR: 20,
    EvidenceStrength.COMMUNITY: 10,
}
_AUTHORITATIVE_MINIMUM = _STRENGTH_RANK[
    EvidenceStrength.TRUSTED_REGISTRY
]


@dataclass(frozen=True)
class VerificationResult:
    release_id: str
    verified: bool
    verified_claim_ids: tuple[str, ...]
    missing_predicates: tuple[str, ...]
    review_exception: ReviewException | None


class VerificationRepository(Protocol):
    def get_release_required(self, release_id: str) -> Release: ...

    def list_claims_for_subject(self, subject_id: str) -> list[Claim]: ...

    def get_evidence(
        self,
        evidence_id: str,
    ) -> EvidenceObservation | None: ...

    def open_review_exception(self, review: ReviewException) -> None: ...

    def append_lifecycle_transition(self, transition) -> None: ...

    def set_release_lifecycle(
        self,
        release_id: str,
        lifecycle: LifecycleState,
    ) -> None: ...


class VerificationService:
    def __init__(self, repository: VerificationRepository):
        self.repository = repository

    def verify_release(
        self,
        release_id: str,
        now: datetime,
    ) -> VerificationResult:
        release = self.repository.get_release_required(release_id)
        claims = [
            claim
            for claim in self.repository.list_claims_for_subject(release_id)
            if claim.state not in {
                ClaimState.REJECTED,
                ClaimState.STALE,
            }
        ]
        by_predicate: dict[str, list[Claim]] = {}
        for claim in claims:
            by_predicate.setdefault(claim.predicate, []).append(claim)

        conflict_claims = self._authoritative_conflicts(by_predicate)
        if conflict_claims:
            evidence_ids = sorted(
                {
                    evidence_id
                    for claim in conflict_claims
                    for evidence_id in claim.evidence_ids
                }
            )
            review = self._conflict_review(
                release_id,
                conflict_claims,
                evidence_ids,
                now,
            )
            self.repository.open_review_exception(review)
            return VerificationResult(
                release_id=release_id,
                verified=False,
                verified_claim_ids=(),
                missing_predicates=(),
                review_exception=review,
            )

        selected: list[Claim] = []
        missing: list[str] = []
        for requirement, predicates in _requirements_for(release.lane).items():
            candidates = [
                claim
                for predicate in predicates
                for claim in by_predicate.get(predicate, [])
            ]
            selected_claim = self._strongest_authoritative(candidates)
            if selected_claim is None:
                missing.append(requirement)
            else:
                selected.append(selected_claim)
        if missing:
            return VerificationResult(
                release_id=release_id,
                verified=False,
                verified_claim_ids=tuple(
                    sorted(claim.id for claim in selected)
                ),
                missing_predicates=tuple(sorted(missing)),
                review_exception=None,
            )

        evidence_ids = sorted(
            {
                evidence_id
                for claim in selected
                for evidence_id in claim.evidence_ids
            }
        )
        if release.lifecycle is LifecycleState.DETECTED:
            LifecycleService(self.repository).transition(
                release_id,
                LifecycleState.VERIFIED,
                reason="Automated verification requirements satisfied",
                evidence_ids=evidence_ids,
                now=now,
            )
        return VerificationResult(
            release_id=release_id,
            verified=True,
            verified_claim_ids=tuple(
                sorted(claim.id for claim in selected)
            ),
            missing_predicates=(),
            review_exception=None,
        )

    def _claim_strength(self, claim: Claim) -> int:
        strengths = [
            _STRENGTH_RANK[evidence.strength]
            for evidence_id in claim.evidence_ids
            if (evidence := self.repository.get_evidence(evidence_id))
            is not None
        ]
        return max(strengths, default=0)

    def _strongest_authoritative(
        self,
        claims: list[Claim],
    ) -> Claim | None:
        ranked = [
            (self._claim_strength(claim), claim)
            for claim in claims
        ]
        ranked = [
            item
            for item in ranked
            if item[0] >= _AUTHORITATIVE_MINIMUM
        ]
        if not ranked:
            return None
        return max(
            ranked,
            key=lambda item: (
                item[0],
                item[1].observed_at,
                item[1].id,
            ),
        )[1]

    def _authoritative_conflicts(
        self,
        by_predicate: dict[str, list[Claim]],
    ) -> list[Claim]:
        conflicts: list[Claim] = []
        for claims in by_predicate.values():
            ranked = [
                (self._claim_strength(claim), claim)
                for claim in claims
            ]
            if not ranked:
                continue
            top_rank = max(rank for rank, _claim in ranked)
            if top_rank < _AUTHORITATIVE_MINIMUM:
                continue
            strongest = [
                claim for rank, claim in ranked if rank == top_rank
            ]
            values = {
                json.dumps(
                    claim.value,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                for claim in strongest
            }
            if len(values) > 1:
                conflicts.extend(strongest)
        return conflicts

    @staticmethod
    def _conflict_review(
        release_id: str,
        claims: list[Claim],
        evidence_ids: list[str],
        now: datetime,
    ) -> ReviewException:
        predicates = sorted({claim.predicate for claim in claims})
        identity = f"{release_id}|{'|'.join(predicates)}"
        review_id = (
            "review:conflicting-authoritative-claims:"
            f"{hashlib.sha256(identity.encode()).hexdigest()}"
        )
        return ReviewException(
            id=review_id,
            subject_id=release_id,
            code="conflicting_authoritative_claims",
            message=(
                "Authoritative evidence conflicts for: "
                f"{', '.join(predicates)}"
            ),
            evidence_ids=evidence_ids,
            opened_at=now,
        )


def _requirements_for(
    lane: ReleaseLane,
) -> dict[str, tuple[str, ...]]:
    if lane is ReleaseLane.MARKET_REFERENCE:
        return {
            "release_identity": (
                "release_date",
                "repo_id",
                "official_url",
            )
        }
    return {
        "license": ("license",),
        "artifact": ("artifact_url", "hf_repo", "repo_id"),
    }
