"""Local workspace endpoints; no identity or session layer."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from radar.api.dependencies import get_repository, get_root, require_writable
from radar.intelligence.alerts import build_alerts
from radar.intelligence.workspaces import (
    Workspace,
    WorkspaceInput,
    WorkspaceService,
)


router = APIRouter(tags=["workspaces"])


@router.get("/workspaces", response_model=list[Workspace])
def list_workspaces(repository: Any = Depends(get_repository)) -> list[Workspace]:
    return repository.list_workspaces()


@router.post(
    "/workspaces",
    response_model=Workspace,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_writable)],
)
def create_workspace(
    value: WorkspaceInput,
    repository: Any = Depends(get_repository),
) -> Workspace:
    return WorkspaceService(repository).create(value)


@router.get("/workspaces/{workspace_id}", response_model=Workspace)
def get_workspace(
    workspace_id: str,
    repository: Any = Depends(get_repository),
) -> Workspace:
    workspace = repository.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown workspace: {workspace_id}",
        )
    return workspace


@router.put(
    "/workspaces/{workspace_id}",
    response_model=Workspace,
    dependencies=[Depends(require_writable)],
)
def update_workspace(
    workspace_id: str,
    value: WorkspaceInput,
    repository: Any = Depends(get_repository),
) -> Workspace:
    try:
        return WorkspaceService(repository).update(workspace_id, value)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown workspace: {workspace_id}",
        ) from exc


@router.delete(
    "/workspaces/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_writable)],
)
def delete_workspace(
    workspace_id: str,
    repository: Any = Depends(get_repository),
) -> None:
    try:
        WorkspaceService(repository).delete(workspace_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown workspace: {workspace_id}",
        ) from exc


@router.get("/workspaces/{workspace_id}/alerts")
def workspace_alerts(
    workspace_id: str,
    repository: Any = Depends(get_repository),
    root: Path = Depends(get_root),
) -> dict[str, Any]:
    """The workspace's stack diffed against the last two weeks of events."""
    workspace = repository.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown workspace: {workspace_id}",
        )
    return build_alerts(
        root,
        devices=workspace.devices,
        stack=workspace.stack,
        now=datetime.now(UTC),
    )
