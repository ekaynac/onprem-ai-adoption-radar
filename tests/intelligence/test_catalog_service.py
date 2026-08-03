from __future__ import annotations

from radar.intelligence.services.container import build_services
from radar.intelligence.workspaces import WorkspaceInput, WorkspaceService

from .lifecycle_helpers import lifecycle_repository
from .test_recommendations import seed_recommendable_release


def test_catalog_search_is_stable_and_workspace_aware(tmp_path) -> None:
    repository = lifecycle_repository(tmp_path)
    seed_recommendable_release(repository)
    workspace = WorkspaceService(repository).create(
        WorkspaceInput(
            name="DC",
            devices=[{"device_id": "hgx-h200-8", "count": 2}],
            policies={"allowed_licenses": ["kimi-k3"]},
        )
    )
    services = build_services(repository)

    first = services.catalog.search("multimodal", workspace_id=workspace.id)
    second = services.catalog.search("multimodal", workspace_id=workspace.id)

    assert first == second
    assert first.items[0].release_id == "release:moonshot-ai:kimi:k3"
    assert first.items[0].workspace_recommendation is not None


def test_catalog_get_uses_keyed_release_lookup(tmp_path, monkeypatch) -> None:
    repository = lifecycle_repository(tmp_path)
    seed_recommendable_release(repository)
    services = build_services(repository)

    def fail_scan():
        raise AssertionError("single-release lookup must not scan the catalog")

    monkeypatch.setattr(repository, "list_all_releases", fail_scan)

    item = services.catalog.get("release:moonshot-ai:kimi:k3")

    assert item.name == "Kimi K3"
