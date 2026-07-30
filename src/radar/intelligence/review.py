"""Review-exception resolution without rewriting raw observations."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


REVIEW_RESOLUTIONS = frozenset(
    {
        "accept_claim",
        "reject_claim",
        "merge_identity",
        "dismiss_candidate",
    }
)


class InvalidReviewResolution(ValueError):
    """A review resolution is unsupported or unaudited."""


class ReviewRepository(Protocol):
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
        self.repository.resolve_review_exception(
            exception_id,
            resolution,
            sorted(set(evidence_ids)),
            now,
        )
