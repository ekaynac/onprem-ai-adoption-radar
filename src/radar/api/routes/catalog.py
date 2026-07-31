"""Catalog search endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query

from radar.api.dependencies import get_root, get_services
from radar.intelligence.contracts import LifecycleState, ModelCategory
from radar.intelligence.recommendations import RecommendationView
from radar.intelligence.services import Page
from radar.intelligence.services.catalog import (
    CatalogDetail,
    CatalogItem,
    ClaimDetail,
)
from radar.intelligence.services.container import IntelligenceServices
from radar.web.intelligence_snapshot import build_public_snapshot


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
    root: Path = Depends(get_root),
) -> Page[CatalogItem]:
    canonical = services.catalog.search(
        q,
        category=category,
        lifecycle=lifecycle,
        workspace_id=workspace_id,
        cursor=cursor,
        limit=100,
    )
    candidates = _candidate_items(services, root)
    tokens = [token for token in q.casefold().replace("-", " ").split() if token]
    filtered = [
        item
        for item in candidates
        if (category is None or item.category is category)
        and (lifecycle is None or item.lifecycle is lifecycle)
        and all(
            token
            in " ".join(
                (
                    item.release_id,
                    item.name,
                    item.category.value,
                    item.lane,
                    item.lifecycle.value,
                )
            ).casefold()
            for token in tokens
        )
    ]
    rows = sorted(
        [*canonical.items, *filtered],
        key=lambda item: item.first_observed_at,
        reverse=True,
    )
    return Page(
        items=rows[:limit],
        next_cursor=(rows[limit - 1].release_id if len(rows) > limit else None),
    )


@router.get("/catalog/{release_id:path}", response_model=CatalogDetail)
def catalog_detail(
    release_id: str,
    workspace_id: str | None = None,
    services: IntelligenceServices = Depends(get_services),
    root: Path = Depends(get_root),
) -> CatalogDetail:
    try:
        return services.catalog.detail(
            release_id,
            workspace_id=workspace_id,
        )
    except KeyError:
        snapshot = build_public_snapshot(
            services,
            datetime.now(UTC),
            root=root,
        )
        model = next(
            (
                item
                for item in snapshot.models
                if item["release_id"] == release_id
                and str(item["release_id"]).startswith("release:hf:")
            ),
            None,
        )
        if model is None:
            raise
        return CatalogDetail(
            release=_candidate_item(model),
            claims=[
                ClaimDetail.model_validate(
                    {
                        **claim,
                        "citations": [
                            {
                                key: value
                                for key, value in citation.items()
                                if key
                                in {
                                    "evidence_id",
                                    "url",
                                    "label",
                                    "strength",
                                }
                            }
                            for citation in claim.get("citations") or []
                        ],
                    }
                )
                for claim in model.get("claims") or []
            ],
            compatibility=[],
            qualification=None,
        )


def _candidate_item(model: dict) -> CatalogItem:
    release_id = str(model["release_id"])
    return CatalogItem(
        release_id=release_id,
        name=str(model["name"]),
        category=ModelCategory(str(model["category"])),
        lane=str(model["lane"]),
        lifecycle=LifecycleState(str(model["lifecycle"])),
        first_observed_at=str(model["first_observed_at"]),
        public_recommendation=RecommendationView(
            release_id=release_id,
            workspace_id=None,
            public_ring=None,
            ring=None,
            reasons=list(model.get("reasons") or []),
            evidence_ids=list(model.get("evidence_ids") or []),
        ),
    )


def _candidate_items(
    services: IntelligenceServices,
    root: Path,
) -> list[CatalogItem]:
    return [
        _candidate_item(model)
        for model in build_public_snapshot(
            services,
            datetime.now(UTC),
            root=root,
        ).models
        if str(model["release_id"]).startswith("release:hf:")
    ]
