def test_release_stream_supports_since_and_workspace(api_client) -> None:
    response = api_client.get(
        "/api/v1/releases",
        params={
            "since": "2026-07-30T08:00:00Z",
            "workspace_id": "workspace:dc",
        },
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["citations"]


def test_unknown_release_is_404(api_client) -> None:
    response = api_client.get("/api/v1/releases/release:missing")

    assert response.status_code == 404
