from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from intelligence.lifecycle_helpers import lifecycle_repository
from intelligence.test_recommendations import seed_recommendable_release
from radar.api.app import create_api_app
from radar.intelligence.services.container import build_services


@pytest.fixture
def api_repository(tmp_path):
    repository = lifecycle_repository(tmp_path)
    seed_recommendable_release(repository)
    return repository


@pytest.fixture
def api_client(tmp_path, api_repository):
    app = create_api_app(
        tmp_path,
        services=build_services(api_repository),
        repository=api_repository,
    )
    return TestClient(app)


@pytest.fixture
def public_api_client(tmp_path, api_repository):
    app = create_api_app(
        tmp_path,
        read_only=True,
        services=build_services(api_repository),
        repository=api_repository,
    )
    return TestClient(app)
