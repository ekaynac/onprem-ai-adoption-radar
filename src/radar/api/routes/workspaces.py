"""Local workspace endpoints; no identity or session layer."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from radar.api.dependencies import get_repository, require_writable
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
