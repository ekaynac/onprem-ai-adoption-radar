def test_public_mode_rejects_mutation(public_api_client) -> None:
    response = public_api_client.post(
        "/api/v1/workspaces",
        json={"name": "Blocked"},
    )

    assert response.status_code == 403


def test_local_mode_creates_workspace_without_login(api_client) -> None:
    response = api_client.post(
        "/api/v1/workspaces",
        json={
            "name": "Architect Lab",
            "devices": [{"device_id": "rtx-4090-24gb", "count": 1}],
        },
    )

    assert response.status_code == 201
    assert response.json()["name"] == "Architect Lab"
