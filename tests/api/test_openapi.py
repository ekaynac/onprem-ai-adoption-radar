def test_openapi_has_versioned_release_and_workspace_routes(api_client) -> None:
    schema = api_client.get("/api/v1/openapi.json").json()

    assert "/api/v1/releases" in schema["paths"]
    assert "/api/v1/workspaces" in schema["paths"]
    assert schema["info"]["version"] == "1.0.0"
