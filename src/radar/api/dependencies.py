"""FastAPI dependencies shared by versioned resource routers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from radar.intelligence.services.container import IntelligenceServices


def get_services(request: Request) -> IntelligenceServices:
    return request.app.state.services


def get_repository(request: Request) -> Any:
    return request.app.state.intelligence_repository


def get_root(request: Request) -> Path:
    return request.app.state.root


def require_writable(request: Request) -> None:
    if request.app.state.read_only:
        raise HTTPException(
            status_code=403,
            detail="This deployment is read-only",
        )
