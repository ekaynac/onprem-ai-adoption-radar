from __future__ import annotations

import pytest

from radar.intelligence.workspaces import (
    UnsupportedWorkspaceVersion,
    WorkspaceInput,
    WorkspaceService,
)

from .lifecycle_helpers import lifecycle_repository


def test_multiple_workspaces_exist_without_users_or_login(tmp_path) -> None:
    service = WorkspaceService(lifecycle_repository(tmp_path))

    laptop = service.create(
        WorkspaceInput(
            name="Laptop Lab",
            devices=[{"device_id": "rtx-4090-24gb", "count": 1}],
            policies={"allowed_licenses": ["apache-2.0", "mit"]},
        )
    )
    datacenter = service.create(
        WorkspaceInput(
            name="H200 Cluster",
            devices=[{"device_id": "hgx-h200-8", "count": 2}],
            policies={
                "allowed_licenses": ["apache-2.0", "mit", "kimi-k3"]
            },
        )
    )

    assert laptop.id != datacenter.id
    assert service.get(laptop.id).name == "Laptop Lab"
    assert service.get(datacenter.id).name == "H200 Cluster"


def test_workspace_document_is_versioned_and_validates_devices(tmp_path) -> None:
    service = WorkspaceService(lifecycle_repository(tmp_path))
    workspace = service.create(
        WorkspaceInput(
            name="Architect Lab",
            devices=[{"device_id": "rtx-4090-24gb", "count": 1}],
        )
    )

    document = service.export_document(workspace.id)
    restored = service.import_document(document)

    assert document["schema_version"] == 1
    assert restored.name == "Architect Lab"
    with pytest.raises(UnsupportedWorkspaceVersion):
        service.import_document({"schema_version": 99, "workspace": {}})
    with pytest.raises(ValueError, match="Unknown device preset"):
        WorkspaceInput(
            name="Invalid",
            devices=[{"device_id": "not-a-device", "count": 1}],
        )
