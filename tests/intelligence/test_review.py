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
