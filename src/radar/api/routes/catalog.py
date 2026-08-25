"""Catalog search endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query

from radar.api.dependencies import get_root, get_services
from radar.constants import CATALOG_FRESHNESS_WINDOW_DAYS
from radar.intelligence.contracts import LifecycleState, ModelCategory, ReleaseLane
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

CATALOG_FRESHNESS_WINDOW_SECONDS = CATALOG_FRESHNESS_WINDOW_DAYS * 24 * 60 * 60


@router.get("/catalog", response_model=Page[CatalogItem])
def search_catalog(
    q: str = "",
    category: ModelCategory | None = None,
    lifecycle: LifecycleState | None = None,
    lane: ReleaseLane | None = None,
    publisher: str | None = None,
    license: str | None = None,
    hardware: str | None = None,
    modality: str | None = None,
    platform: str | None = None,
    freshness: str | None = Query(default=None, pattern="^(fresh|stale)$"),
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
        lane=lane.value if lane is not None else None,
        publisher=publisher,
        license=license,
        hardware=hardware,
        modality=modality,
        platform=platform,
        freshness=freshness,
        now=datetime.now(UTC),
        workspace_id=workspace_id,
        cursor=cursor,
        limit=100,
    )
    now = datetime.now(UTC)
    candidate_models = _candidate_models(services, root, now)
    tokens = [token for token in q.casefold().replace("-", " ").split() if token]
    filtered: list[CatalogItem] = []
    for model in candidate_models:
        item = _candidate_item(model)
        haystack = " ".join(
            (
                item.release_id,
                item.name,
                item.category.value,
                item.lane,
                item.lifecycle.value,
            )
        ).casefold()
        if not (
            (category is None or item.category is category)
            and (lifecycle is None or item.lifecycle is lifecycle)
            and all(token in haystack for token in tokens)
            and (lane is None or item.lane == lane.value)
            and _candidate_matches_metadata(
                model,
                publisher=publisher,
                license=license,
                hardware=hardware,
                modality=modality,
                platform=platform,
                freshness=freshness,
                now=now,
            )
        ):
            continue
        filtered.append(item)
    rows = sorted(
        [*canonical.items, *filtered],
        key=lambda item: item.first_observed_at,
        reverse=True,
    )
    return Page(
        items=rows[:limit],
        next_cursor=(rows[limit - 1].release_id if len(rows) > limit else None),
    )


@router.get("/catalog/facets", response_model=dict[str, list[str]])
def catalog_facets(
    services: IntelligenceServices = Depends(get_services),
) -> dict[str, list[str]]:
    return services.catalog.facets()


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


def _candidate_models(
    services: IntelligenceServices,
    root: Path,
    now: datetime,
) -> list[dict]:
    return [
        model
        for model in build_public_snapshot(
            services,
            now,
            root=root,
        ).models
        if str(model["release_id"]).startswith("release:hf:")
    ]


def _candidate_matches_metadata(
    model: dict,
    *,
    publisher: str | None,
    license: str | None,
    hardware: str | None,
    modality: str | None,
    platform: str | None,
    freshness: str | None,
    now: datetime,
) -> bool:
    profile = model.get("profile") or {}
    candidate_publisher = profile.get("publisher") or profile.get("family")
    if publisher is not None and candidate_publisher != publisher:
        return False
    if license is not None and profile.get("license") != license:
        return False
    if hardware is not None and profile.get("hardware_tier") != hardware:
        return False
    if modality is not None and profile.get("modality") != modality:
        return False
    if platform is not None and profile.get("library_name") != platform:
        return False
    if freshness is not None:
        raw = model.get("released_at") or model.get("first_observed_at")
        try:
            released_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return freshness == "stale"
        is_fresh = (now - released_at).total_seconds() <= CATALOG_FRESHNESS_WINDOW_SECONDS
        if (freshness == "fresh") != is_fresh:
            return False
    return True
