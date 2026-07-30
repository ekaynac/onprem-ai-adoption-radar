"""Integration capabilities and public delivery projections."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response

from radar.api.dependencies import get_repository, get_services
from radar.intelligence.services.container import IntelligenceServices
from radar.reports.intelligence_feeds import (
    render_intelligence_atom,
    render_intelligence_json_feed,
    render_intelligence_rss,
)
from radar.web.intelligence_snapshot import build_public_snapshot


router = APIRouter(tags=["integrations"])


@router.get("/integrations")
def integrations() -> dict[str, list[str]]:
    return {
        "sources": [
            "huggingface",
            "github_releases",
            "official_feeds",
            "announcement_pages",
            "json_registries",
            "evidence",
        ],
        "transports": ["rest", "mcp", "rss", "atom", "webhooks"],
    }


def _public_events(repository):
    return repository.list_events(limit=500, public_only=True)


@router.get("/integrations/feed.atom")
def intelligence_atom(
    request: Request,
    repository=Depends(get_repository),
) -> Response:
    body = render_intelligence_atom(
        _public_events(repository),
        str(request.base_url).rstrip("/"),
    )
    return Response(content=body, media_type="application/atom+xml")


@router.get("/integrations/feed.rss")
def intelligence_rss(
    request: Request,
    repository=Depends(get_repository),
) -> Response:
    body = render_intelligence_rss(
        _public_events(repository),
        str(request.base_url).rstrip("/"),
    )
    return Response(content=body, media_type="application/rss+xml")


@router.get("/integrations/feed.json")
def intelligence_json_feed(
    request: Request,
    repository=Depends(get_repository),
) -> Response:
    body = render_intelligence_json_feed(
        _public_events(repository),
        str(request.base_url).rstrip("/"),
    )
    return Response(content=body, media_type="application/feed+json")


@router.get("/integrations/public-snapshot")
def public_snapshot(
    services: IntelligenceServices = Depends(get_services),
):
    return build_public_snapshot(services, datetime.now(UTC))
