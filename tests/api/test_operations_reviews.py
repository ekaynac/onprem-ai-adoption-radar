from intelligence.lifecycle_helpers import NOW, RELEASE_ID
from intelligence.test_verification import seed_claim
from radar.intelligence.contracts import ReviewException


def test_review_queue_lists_and_resolves_exception(
    api_client,
    api_repository,
) -> None:
    seed_claim(
        api_repository,
        "claim:review:license:one",
        "license",
        "mit",
        "review-one",
    )
    seed_claim(
        api_repository,
        "claim:review:license:two",
        "license",
        "proprietary",
        "review-two",
    )
    review = ReviewException(
        id="review:kimi:license",
        subject_id=RELEASE_ID,
        code="conflicting_authoritative_claims",
        message="Official license claims differ",
        evidence_ids=["evidence:review-one", "evidence:review-two"],
        opened_at=NOW,
    )
    api_repository.open_review_exception(review)

    listed = api_client.get("/api/v1/operations/reviews")
    resolved = api_client.post(
        f"/api/v1/operations/reviews/{review.id}/resolve",
        json={
            "resolution": "accept_claim",
            "evidence_ids": ["evidence:review-one"],
        },
    )

    assert listed.status_code == 200
    assert listed.json()[0]["id"] == review.id
    assert resolved.status_code == 200
    assert resolved.json()["resolved_at"] is not None
