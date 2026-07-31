"""Review-exception resolution without rewriting raw observations."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Protocol

from radar.intelligence.contracts import Claim, ClaimState, ReviewException
from radar.intelligence.verification import (
    VerificationRepository,
    VerificationService,
)


REVIEW_RESOLUTIONS = frozenset(
    {
        "accept_claim",
        "reject_claim",
        "dismiss_candidate",
    }
)


class InvalidReviewResolution(ValueError):
    """A review resolution is unsupported or unaudited."""


class ReviewRepository(VerificationRepository, Protocol):
    def get_review_exception(
        self,
        exception_id: str,
    ) -> ReviewException | None: ...

    def resolve_review_exception(
        self,
        exception_id: str,
        resolution: str,
        evidence_ids: list[str],
        now: datetime,
    ) -> None: ...


class ReviewService:
    def __init__(self, repository: ReviewRepository):
        self.repository = repository

    def resolve(
        self,
        exception_id: str,
        resolution: str,
        *,
        evidence_ids: list[str],
        now: datetime,
    ) -> None:
        if resolution not in REVIEW_RESOLUTIONS:
            raise InvalidReviewResolution(
                f"Unknown review resolution: {resolution}"
            )
        if not evidence_ids:
            raise InvalidReviewResolution(
                "Review resolutions require evidence"
            )
        review = self.repository.get_review_exception(exception_id)
        if review is None:
            raise InvalidReviewResolution(
                f"Unknown review exception: {exception_id}"
            )
        if resolution in {"accept_claim", "reject_claim"}:
            if len(set(evidence_ids)) != 1:
                raise InvalidReviewResolution(
                    "Claim resolutions require exactly one selected evidence record"
                )
            claims = self._review_claims(review)
            selected_evidence = evidence_ids[0]
            selected = [
                claim
                for claim in claims
                if selected_evidence in claim.evidence_ids
            ]
            if not selected:
                raise InvalidReviewResolution(
                    "Selected evidence does not identify a disputed claim"
                )
            if resolution == "accept_claim":
                selected_ids = {claim.id for claim in selected}
                selected_predicates = {
                    claim.predicate for claim in selected
                }
                for claim in selected:
                    self.repository.set_claim_state(
                        claim.id,
                        ClaimState.VERIFIED,
                    )
                for other in claims:
                    if (
                        other.id not in selected_ids
                        and other.predicate in selected_predicates
                    ):
                        self.repository.set_claim_state(
                            other.id,
                            ClaimState.REJECTED,
                        )
            else:
                for claim in selected:
                    self.repository.set_claim_state(
                        claim.id,
                        ClaimState.REJECTED,
                    )
        self.repository.resolve_review_exception(
            exception_id,
            resolution,
            sorted(set(evidence_ids)),
            now,
        )
        if resolution == "accept_claim":
            VerificationService(self.repository).verify_release(
                review.subject_id,
                now,
            )

    def _review_claims(self, review: ReviewException) -> list[Claim]:
        claims = [
            claim
            for claim in self.repository.list_claims_for_subject(
                review.subject_id
            )
            if set(claim.evidence_ids) & set(review.evidence_ids)
        ]
        disputed_predicates = {
            predicate
            for predicate in {claim.predicate for claim in claims}
            if len(
                {
                    json.dumps(
                        claim.value,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    for claim in claims
                    if claim.predicate == predicate
                }
            )
            > 1
        }
        return [
            claim
            for claim in claims
            if claim.predicate in disputed_predicates
        ]
