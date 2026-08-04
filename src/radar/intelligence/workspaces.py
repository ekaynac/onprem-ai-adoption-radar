"""Versioned local workspace contexts; deliberately no user or login model."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from radar.intelligence.contracts import FrozenModel
from radar.models_radar.devices import resolve_device


WORKSPACE_SCHEMA_VERSION = 1


class UnsupportedWorkspaceVersion(ValueError):
    """A workspace document uses an unsupported schema version."""


class WorkspaceDevice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str | None = None
    custom_device: dict[str, Any] | None = None
    count: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_device(self) -> WorkspaceDevice:
        if (self.device_id is None) == (self.custom_device is None):
            raise ValueError(
                "Exactly one of device_id or custom_device is required"
            )
        resolve_device(
            self.device_id
            if self.device_id is not None
            else self.custom_device or {}
        )
        return self


class WorkspaceEngine(BaseModel):
    """One running serving/tooling component, optionally version-pinned."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=60)
    version: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def normalize(self) -> WorkspaceEngine:
        object.__setattr__(self, "name", self.name.strip().casefold())
        return self


class WorkspaceStack(BaseModel):
    """The running stack: engines + production models + quant formats.

    This is what alerts diff events against — a change only matters if
    it touches something listed here (or the estate's devices).
    """

    model_config = ConfigDict(extra="forbid")

    engines: list[WorkspaceEngine] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    quant_formats: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize(self) -> WorkspaceStack:
        object.__setattr__(
            self,
            "models",
            [value.strip().casefold() for value in self.models if value.strip()],
        )
        object.__setattr__(
            self,
            "quant_formats",
            [
                value.strip().casefold()
                for value in self.quant_formats
                if value.strip()
            ],
        )
        return self


class WorkspaceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    devices: list[WorkspaceDevice] = Field(default_factory=list)
    workloads: list[dict[str, Any]] = Field(default_factory=list)
    policies: dict[str, Any] = Field(default_factory=dict)
    watchlists: list[dict[str, Any]] = Field(default_factory=list)
    stack: WorkspaceStack = Field(default_factory=WorkspaceStack)


class Workspace(FrozenModel):
    id: str
    schema_version: int = WORKSPACE_SCHEMA_VERSION
    name: str
    devices: list[WorkspaceDevice] = Field(default_factory=list)
    workloads: list[dict[str, Any]] = Field(default_factory=list)
    policies: dict[str, Any] = Field(default_factory=dict)
    watchlists: list[dict[str, Any]] = Field(default_factory=list)
    stack: WorkspaceStack = Field(default_factory=WorkspaceStack)


class WorkspaceRepository(Protocol):
    def create_workspace(self, workspace: Workspace) -> Workspace: ...

    def get_workspace(self, workspace_id: str) -> Workspace | None: ...

    def update_workspace(self, workspace: Workspace) -> Workspace: ...

    def delete_workspace(self, workspace_id: str) -> bool: ...


class WorkspaceService:
    def __init__(self, repository: WorkspaceRepository):
        self.repository = repository

    def create(self, value: WorkspaceInput) -> Workspace:
        workspace = Workspace(
            id=f"workspace:{uuid4()}",
            schema_version=WORKSPACE_SCHEMA_VERSION,
            **value.model_dump(mode="python"),
        )
        return self.repository.create_workspace(workspace)

    def get(self, workspace_id: str) -> Workspace:
        workspace = self.repository.get_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Unknown workspace: {workspace_id}")
        return workspace

    def update(self, workspace_id: str, value: WorkspaceInput) -> Workspace:
        existing = self.get(workspace_id)
        workspace = Workspace(
            id=existing.id,
            schema_version=WORKSPACE_SCHEMA_VERSION,
            **value.model_dump(mode="python"),
        )
        return self.repository.update_workspace(workspace)

    def delete(self, workspace_id: str) -> None:
        if not self.repository.delete_workspace(workspace_id):
            raise KeyError(f"Unknown workspace: {workspace_id}")

    def export_document(self, workspace_id: str) -> dict[str, Any]:
        workspace = self.get(workspace_id)
        payload = workspace.model_dump(mode="json")
        payload.pop("id")
        payload.pop("schema_version")
        return {
            "schema_version": WORKSPACE_SCHEMA_VERSION,
            "workspace": payload,
        }

    def import_document(self, document: dict[str, Any]) -> Workspace:
        version = document.get("schema_version")
        if version != WORKSPACE_SCHEMA_VERSION:
            raise UnsupportedWorkspaceVersion(
                f"Unsupported workspace schema version: {version}"
            )
        payload = WorkspaceInput.model_validate(document.get("workspace"))
        return self.create(payload)
