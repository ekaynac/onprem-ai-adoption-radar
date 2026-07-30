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
