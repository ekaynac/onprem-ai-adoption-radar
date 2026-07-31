from datetime import UTC, datetime

from radar.storage.model_candidate_log import (
    ModelCandidateObservation,
    append_model_candidates,
)


def test_catalog_detail_exposes_claim_state_and_citations(
    api_client,
) -> None:
    response = api_client.get(
        "/api/v1/catalog/release:moonshot-ai:kimi:k3"
    )

    assert response.status_code == 200
    payload = response.json()
    license_claim = next(
        claim for claim in payload["claims"] if claim["predicate"] == "license"
    )
    assert license_claim["state"] == "verified"
    assert license_claim["citations"][0]["url"] == "https://moonshot.ai/kimi-k3"
    assert payload["release"]["name"] == "Kimi K3"
    assert "compatibility" in payload


def test_catalog_and_detail_include_fresh_hf_candidates(
    api_client,
    tmp_path,
) -> None:
    append_model_candidates(
        tmp_path / "data" / "model-candidate-observations.jsonl",
        [
            ModelCandidateObservation(
                hf_repo="moonshotai/Kimi-K3",
                name="Kimi-K3",
                family="moonshotai",
                downloads=1,
                pipeline_tag="image-text-to-text",
                observed_at=datetime.now(UTC),
            )
        ],
    )

    listing = api_client.get("/api/v1/catalog", params={"q": "Kimi-K3"})
    release_id = listing.json()["items"][0]["release_id"]
    detail = api_client.get(f"/api/v1/catalog/{release_id}")

    assert listing.status_code == 200
    assert detail.status_code == 200
    assert detail.json()["release"]["name"] == "Kimi-K3"
    assert detail.json()["claims"]
