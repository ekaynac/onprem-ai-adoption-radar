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


def test_catalog_facets_are_available_before_the_detail_catchall(api_client) -> None:
    response = api_client.get("/api/v1/catalog/facets")

    assert response.status_code == 200
    assert response.json()["publisher"] == ["publisher:moonshot-ai"]
    assert response.json()["license"] == ["kimi-k3"]


def test_catalog_filters_apply_to_live_hf_candidates(api_client, tmp_path) -> None:
    append_model_candidates(
        tmp_path / "data" / "model-candidate-observations.jsonl",
        [
            ModelCandidateObservation(
                hf_repo="moonshotai/Kimi-K3",
                name="Kimi-K3",
                family="moonshotai",
                downloads=1,
                pipeline_tag="image-text-to-text",
                last_modified="2026-07-01T00:00:00Z",
                observed_at=datetime.now(UTC),
            )
        ],
    )

    publisher = api_client.get(
        "/api/v1/catalog",
        params={"q": "Kimi-K3", "publisher": "moonshotai"},
    )
    unsupported_license = api_client.get(
        "/api/v1/catalog",
        params={"q": "Kimi-K3", "license": "apache-2.0"},
    )
    modality = api_client.get(
        "/api/v1/catalog",
        params={"q": "Kimi-K3", "modality": "image-text-to-text"},
    )
    stale = api_client.get(
        "/api/v1/catalog",
        params={"q": "Kimi-K3", "freshness": "stale"},
    )

    assert [item["name"] for item in publisher.json()["items"]] == ["Kimi-K3"]
    assert unsupported_license.json()["items"] == []
    assert [item["name"] for item in modality.json()["items"]] == ["Kimi-K3"]
    assert [item["name"] for item in stale.json()["items"]] == ["Kimi-K3"]
