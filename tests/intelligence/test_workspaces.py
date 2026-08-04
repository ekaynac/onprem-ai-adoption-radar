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


def test_stack_profile_round_trips_and_normalizes(tmp_path) -> None:
    service = WorkspaceService(lifecycle_repository(tmp_path))

    workspace = service.create(
        WorkspaceInput(
            name="Prod stack",
            devices=[{"device_id": "rtx-4090-24gb", "count": 2}],
            stack={
                "engines": [{"name": "  vLLM ", "version": "0.10"}],
                "models": ["Qwen3-32B", " deepseek-r1 "],
                "quant_formats": ["GGUF", ""],
            },
        )
    )

    assert workspace.stack.engines[0].name == "vllm"
    assert workspace.stack.models == ["qwen3-32b", "deepseek-r1"]
    assert workspace.stack.quant_formats == ["gguf"]
    # Export/import keeps the stack (schema stays v1 — additive field).
    restored = service.import_document(service.export_document(workspace.id))
    assert restored.stack == workspace.stack
    # Pre-stack documents (no `stack` key) still import cleanly.
    legacy = service.export_document(workspace.id)
    legacy["workspace"].pop("stack")
    assert service.import_document(legacy).stack.engines == []


def test_workspace_update_and_delete_round_trip(tmp_path) -> None:
    import pytest

    service = WorkspaceService(lifecycle_repository(tmp_path))
    workspace = service.create(
        WorkspaceInput(
            name="Before",
            devices=[{"device_id": "rtx-4090-24gb", "count": 1}],
        )
    )

    updated = service.update(
        workspace.id,
        WorkspaceInput(
            name="After",
            devices=[{"device_id": "a100-80gb", "count": 2}],
            stack={"engines": [{"name": "vllm"}], "models": ["qwen3-32b"]},
        ),
    )

    assert updated.id == workspace.id
    stored = service.get(workspace.id)
    assert stored.name == "After"
    assert stored.devices[0].device_id == "a100-80gb"
    assert stored.stack.models == ["qwen3-32b"]

    service.delete(workspace.id)
    with pytest.raises(KeyError):
        service.get(workspace.id)
    with pytest.raises(KeyError):
        service.delete(workspace.id)
    with pytest.raises(KeyError):
        service.update(workspace.id, WorkspaceInput(name="Ghost"))
