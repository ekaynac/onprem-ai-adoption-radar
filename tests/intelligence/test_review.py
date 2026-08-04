from __future__ import annotations

from radar.intelligence.contracts import ReviewException
from radar.intelligence.review import ReviewService

from .lifecycle_helpers import NOW, RELEASE_ID, lifecycle_repository
from .test_verification import seed_claim


def test_review_resolution_is_append_audited(tmp_path) -> None:
    repository = lifecycle_repository(tmp_path)
    seed_claim(repository, "claim:license:one", "license", "mit", "one")
    seed_claim(
        repository,
        "claim:license:two",
        "license",
        "proprietary",
        "two",
    )
    review = ReviewException(
        id="review:kimi:license",
        subject_id=RELEASE_ID,
        code="conflicting_authoritative_claims",
        message="Official license claims differ",
        evidence_ids=["evidence:one", "evidence:two"],
        opened_at=NOW,
    )
    repository.open_review_exception(review)
    service = ReviewService(repository)

    service.resolve(
        review.id,
        "accept_claim",
        evidence_ids=["evidence:one"],
        now=NOW,
    )

    resolved = repository.get_review_exception(review.id)
    assert resolved is not None
    assert resolved.resolved_at == NOW
    assert repository.get_review_resolution(review.id) == {
        "resolution": "accept_claim",
        "evidence_ids": ["evidence:one"],
    }
    assert repository.get_claim("claim:license:one").state.value == "verified"
    assert repository.get_claim("claim:license:two").state.value == "rejected"


def test_reopening_a_review_is_idempotent_across_runs(tmp_path) -> None:
    """Production repro: the same ambiguous candidate re-encountered on a
    later scan re-opens its identity review with a new timestamp and new
    per-run evidence — that must be a no-op, not a RepositoryConflict.
    A resolved review must also stand (human decisions are never reopened).
    """
    from datetime import UTC, datetime, timedelta

    import pytest

    from radar.intelligence.contracts import ReviewException
    from radar.intelligence.repositories import RepositoryConflict

    repository = lifecycle_repository(tmp_path)
    opened = datetime(2026, 8, 3, 11, 0, tzinfo=UTC)
    first = ReviewException(
        id="review:identity:abc123",
        subject_id="candidate:hf:acme/model",
        code="ambiguous_identity",
        message="Identity review required for Model",
        evidence_ids=["evidence:hf:run-1"],
        opened_at=opened,
    )
    repository.open_review_exception(first)

    # Next scan: same identity, new timestamp + evidence → idempotent.
    repository.open_review_exception(
        first.model_copy(
            update={
                "opened_at": opened + timedelta(hours=2),
                "evidence_ids": ["evidence:hf:run-2"],
            }
        )
    )
    stored = repository.get_review_exception("review:identity:abc123")
    assert stored is not None
    assert stored.opened_at == opened  # first-opened wins
    assert stored.evidence_ids == ["evidence:hf:run-1"]

    # A genuinely different subject under the same id is still a conflict.
    with pytest.raises(RepositoryConflict):
        repository.open_review_exception(
            first.model_copy(update={"subject_id": "candidate:hf:other/model"})
        )
