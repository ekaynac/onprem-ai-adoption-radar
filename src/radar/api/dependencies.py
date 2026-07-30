"""FastAPI dependencies shared by versioned resource routers."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from radar.intelligence.services.container import IntelligenceServices


def get_services(request: Request) -> IntelligenceServices:
    return request.app.state.services


def get_repository(request: Request) -> Any:
    return request.app.state.intelligence_repository


def require_writable(request: Request) -> None:
    if request.app.state.read_only:
        raise HTTPException(
            status_code=403,
            detail="This deployment is read-only",
        )
