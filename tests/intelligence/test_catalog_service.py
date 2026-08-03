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


def test_catalog_filters_and_facets_use_claim_metadata(tmp_path) -> None:
    repository = lifecycle_repository(tmp_path)
    seed_recommendable_release(repository)
    services = build_services(repository)

    matching = services.catalog.search(
        "",
        publisher="publisher:moonshot-ai",
        license="kimi-k3",
        modality="multimodal",
        lane="deployable_onprem",
    )
    excluded = services.catalog.search("", license="apache-2.0")
    facets = services.catalog.facets()

    assert [item.release_id for item in matching.items] == [
        "release:moonshot-ai:kimi:k3"
    ]
    assert excluded.items == []
    assert facets["publisher"] == ["publisher:moonshot-ai"]
    assert facets["license"] == ["kimi-k3"]
    assert facets["modality"] == ["multimodal"]
