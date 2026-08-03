"""Release stream endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query

from radar.api.dependencies import get_root, get_services
from radar.intelligence.services import Page
from radar.intelligence.services.container import IntelligenceServices
from radar.intelligence.services.releases import ReleaseChange
from radar.web.intelligence_snapshot import build_public_snapshot


router = APIRouter(tags=["releases"])


@router.get("/releases", response_model=Page[ReleaseChange])
def list_releases(
    since: datetime | None = None,
    workspace_id: str | None = None,
    priority_only: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    services: IntelligenceServices = Depends(get_services),
    root: Path = Depends(get_root),
) -> Page[ReleaseChange]:
    del workspace_id
    now = datetime.now(UTC)
    rows = [
        ReleaseChange.model_validate(item)
        for item in build_public_snapshot(
            services,
            now,
            root=root,
        ).releases
        if since is None
        or datetime.fromisoformat(str(item["first_observed_at"])) >= since
    ]
    if priority_only:
        rows = [
            item
            for item in rows
            if item.confidence >= 0.7 and item.review_status == "clear"
        ]
        rows.sort(
            key=lambda item: (
                item.confidence,
                item.released_at or item.first_observed_at,
            ),
            reverse=True,
        )
    return Page(
        items=rows[:limit],
        next_cursor=(rows[limit - 1].release_id if len(rows) > limit else None),
    )


@router.get("/releases/{release_id:path}", response_model=ReleaseChange)
def get_release(
    release_id: str,
    services: IntelligenceServices = Depends(get_services),
    root: Path = Depends(get_root),
) -> ReleaseChange:
    now = datetime.now(UTC)
    try:
        return services.releases.get(release_id, now=now)
    except KeyError:
        candidate = next(
            (
                item
                for item in build_public_snapshot(
                    services,
                    now,
                    root=root,
                ).releases
                if item["release_id"] == release_id
            ),
            None,
        )
        if candidate is None:
            raise
        return ReleaseChange.model_validate(candidate)
