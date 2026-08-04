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


def test_workspace_alerts_diff_events_against_the_stack(
    api_client, tmp_path
) -> None:
    import json

    created = api_client.post(
        "/api/v1/workspaces",
        json={
            "name": "Prod stack",
            "devices": [{"device_id": "rtx-4090-24gb", "count": 1}],
            "stack": {
                "engines": [{"name": "vllm", "version": "0.10"}],
                "models": ["qwen3-32b"],
                "quant_formats": ["gguf"],
            },
        },
    )
    assert created.status_code == 201
    workspace_id = created.json()["id"]

    from datetime import UTC, datetime, timedelta

    recent = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "news-observations.jsonl").write_text(
        json.dumps(
            {
                "id": "news:vllm-break",
                "source_id": "vllm-blog",
                "title": "vLLM drops V0 engine",
                "url": "https://blog.vllm.ai/v0-removal",
                "summary": "V0 removed",
                "published_at": recent,
                "observed_at": recent,
            }
        )
        + "\n"
    )
    (data / "news-classified.jsonl").write_text(
        json.dumps(
            {
                "news_id": "news:vllm-break",
                "relevant": True,
                "event_type": "breaking-change",
                "components": ["vllm"],
                "operational_impact": "breaking",
                "summary": "V0 removed; migrate.",
                "citation": "https://blog.vllm.ai/v0-removal",
                "model": "claude-opus-5",
                "classified_at": recent,
            }
        )
        + "\n"
    )

    response = api_client.get(f"/api/v1/workspaces/{workspace_id}/alerts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["counts"]["act"] == 1
    assert payload["alerts"][0]["subject"] == "vLLM drops V0 engine"

    missing = api_client.get("/api/v1/workspaces/workspace:nope/alerts")
    assert missing.status_code == 404


def test_workspace_update_and_delete_endpoints(api_client) -> None:
    created = api_client.post(
        "/api/v1/workspaces", json={"name": "Before"}
    ).json()

    updated = api_client.put(
        f"/api/v1/workspaces/{created['id']}",
        json={
            "name": "After",
            "stack": {"engines": [{"name": "vllm", "version": "0.10"}]},
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "After"
    assert updated.json()["stack"]["engines"][0]["name"] == "vllm"

    missing = api_client.put(
        "/api/v1/workspaces/workspace:nope", json={"name": "X"}
    )
    assert missing.status_code == 404

    deleted = api_client.delete(f"/api/v1/workspaces/{created['id']}")
    assert deleted.status_code == 204
    assert (
        api_client.get(f"/api/v1/workspaces/{created['id']}").status_code
        == 404
    )
    assert (
        api_client.delete(f"/api/v1/workspaces/{created['id']}").status_code
        == 404
    )


def test_public_mode_rejects_update_and_delete(public_api_client) -> None:
    assert (
        public_api_client.put(
            "/api/v1/workspaces/workspace:x", json={"name": "X"}
        ).status_code
        == 403
    )
    assert (
        public_api_client.delete("/api/v1/workspaces/workspace:x").status_code
        == 403
    )
