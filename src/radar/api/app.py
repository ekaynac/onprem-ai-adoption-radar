"""FastAPI factory for the versioned intelligence API."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from radar.api.routes import ROUTERS
from radar.intelligence.bootstrap import build_intelligence_repository
from radar.intelligence.repositories import RepositoryConflict
from radar.intelligence.services.container import (
    IntelligenceServices,
    build_services,
)


def create_api_app(
    root: Path,
    *,
    read_only: bool = False,
    services: IntelligenceServices | None = None,
    repository: Any | None = None,
) -> FastAPI:
    app = FastAPI(
        title="On-Prem Intelligence API",
        version="1.0.0",
        docs_url="/api/docs",
        openapi_url="/api/v1/openapi.json",
    )
    if repository is None:
        _database, repository = build_intelligence_repository(root)
    app.state.intelligence_repository = repository
    app.state.services = services or build_services(repository)
    app.state.read_only = read_only

    @app.exception_handler(KeyError)
    async def not_found(_request: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc).strip("'")},
        )

    @app.exception_handler(RepositoryConflict)
    async def conflict(
        _request: Request,
        exc: RepositoryConflict,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc)},
        )

    @app.middleware("http")
    async def optional_api_token(request: Request, call_next):
        token = os.getenv("RADAR_API_TOKEN")
        if (
            token
            and not request.app.state.read_only
            and request.method not in {"GET", "HEAD", "OPTIONS"}
            and request.headers.get("authorization") != f"Bearer {token}"
        ):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API token"},
            )
        return await call_next(request)

    for router in ROUTERS:
        app.include_router(router, prefix="/api/v1")
    return app
