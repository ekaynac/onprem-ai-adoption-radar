"""Release stream endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query

from radar.api.dependencies import get_services
from radar.intelligence.services import Page
from radar.intelligence.services.container import IntelligenceServices
from radar.intelligence.services.releases import ReleaseChange


router = APIRouter(tags=["releases"])


@router.get("/releases", response_model=Page[ReleaseChange])
def list_releases(
    since: datetime | None = None,
    workspace_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    services: IntelligenceServices = Depends(get_services),
) -> Page[ReleaseChange]:
    del workspace_id
    now = datetime.now(UTC)
    return services.releases.list_changes(
        since=since or now - timedelta(days=7),
        limit=limit,
        now=now,
    )


@router.get("/releases/{release_id:path}", response_model=ReleaseChange)
def get_release(
    release_id: str,
    services: IntelligenceServices = Depends(get_services),
) -> ReleaseChange:
    return services.releases.get(release_id, now=datetime.now(UTC))
