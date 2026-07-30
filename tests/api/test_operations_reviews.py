from intelligence.lifecycle_helpers import NOW, RELEASE_ID
from radar.intelligence.contracts import ReviewException


def test_review_queue_lists_and_resolves_exception(
    api_client,
    api_repository,
) -> None:
    review = ReviewException(
        id="review:kimi:license",
        subject_id=RELEASE_ID,
        code="conflicting_authoritative_claims",
        message="Official license claims differ",
        evidence_ids=["evidence:qualification"],
        opened_at=NOW,
    )
    api_repository.open_review_exception(review)

    listed = api_client.get("/api/v1/operations/reviews")
    resolved = api_client.post(
        f"/api/v1/operations/reviews/{review.id}/resolve",
        json={
            "resolution": "accept_claim",
            "evidence_ids": ["evidence:qualification"],
        },
    )

    assert listed.status_code == 200
    assert listed.json()[0]["id"] == review.id
    assert resolved.status_code == 200
    assert resolved.json()["resolved_at"] is not None
