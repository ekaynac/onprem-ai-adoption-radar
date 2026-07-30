"""Catalog search endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from radar.api.dependencies import get_services
from radar.intelligence.contracts import LifecycleState, ModelCategory
from radar.intelligence.services import Page
from radar.intelligence.services.catalog import CatalogDetail, CatalogItem
from radar.intelligence.services.container import IntelligenceServices


router = APIRouter(tags=["catalog"])


@router.get("/catalog", response_model=Page[CatalogItem])
def search_catalog(
    q: str = "",
    category: ModelCategory | None = None,
    lifecycle: LifecycleState | None = None,
    workspace_id: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    services: IntelligenceServices = Depends(get_services),
) -> Page[CatalogItem]:
    return services.catalog.search(
        q,
        category=category,
        lifecycle=lifecycle,
        workspace_id=workspace_id,
        cursor=cursor,
        limit=limit,
    )


@router.get("/catalog/{release_id:path}", response_model=CatalogDetail)
def catalog_detail(
    release_id: str,
    workspace_id: str | None = None,
    services: IntelligenceServices = Depends(get_services),
) -> CatalogDetail:
    return services.catalog.detail(
        release_id,
        workspace_id=workspace_id,
    )
