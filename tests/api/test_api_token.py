from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def token_client(api_client) -> TestClient:
    return api_client


def test_write_requires_bearer_token_when_set(
    api_repository, tmp_path, monkeypatch
) -> None:
    from fastapi.testclient import TestClient

    from radar.api.app import create_api_app
    from radar.intelligence.services.container import build_services

    monkeypatch.setenv("RADAR_API_TOKEN", "secret-token")
    app = create_api_app(
        tmp_path,
        services=build_services(api_repository),
        repository=api_repository,
    )
    client = TestClient(app)

    denied = client.post("/api/v1/workspaces", json={"name": "X"})
    assert denied.status_code == 401

    wrong = client.post(
        "/api/v1/workspaces",
        json={"name": "X"},
        headers={"authorization": "Bearer wrong"},
    )
    assert wrong.status_code == 401

    ok = client.post(
        "/api/v1/workspaces",
        json={"name": "Token Lab"},
        headers={"authorization": "Bearer secret-token"},
    )
    assert ok.status_code == 201


def test_reads_stay_open_when_token_is_set(
    api_repository, tmp_path, monkeypatch
) -> None:
    from fastapi.testclient import TestClient

    from radar.api.app import create_api_app
    from radar.intelligence.services.container import build_services

    monkeypatch.setenv("RADAR_API_TOKEN", "secret-token")
    app = create_api_app(
        tmp_path,
        services=build_services(api_repository),
        repository=api_repository,
    )
    client = TestClient(app)

    assert client.get("/api/v1/workspaces").status_code == 200
    assert client.get("/api/v1/healthz").json() == {"status": "ok"}


def test_read_only_mode_ignores_token_requirement(
    api_repository, tmp_path, monkeypatch
) -> None:
    from fastapi.testclient import TestClient

    from radar.api.app import create_api_app
    from radar.intelligence.services.container import build_services

    monkeypatch.setenv("RADAR_API_TOKEN", "secret-token")
    app = create_api_app(
        tmp_path,
        read_only=True,
        services=build_services(api_repository),
        repository=api_repository,
    )
    client = TestClient(app)

    # read_only mode rejects mutations with its own 403 before auth matters.
    response = client.post(
        "/api/v1/workspaces",
        json={"name": "Blocked"},
        headers={"authorization": "Bearer secret-token"},
    )
    assert response.status_code == 403


def test_no_token_env_means_open_writes(api_client, monkeypatch) -> None:
    monkeypatch.delenv("RADAR_API_TOKEN", raising=False)
    response = api_client.post("/api/v1/workspaces", json={"name": "Open"})
    assert response.status_code == 201
