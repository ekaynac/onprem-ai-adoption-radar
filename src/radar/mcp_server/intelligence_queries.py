"""Context-efficient MCP façade over shared intelligence services."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from radar.intelligence.services.container import IntelligenceServices
from radar.intelligence.sources.utils import parse_datetime


class IntelligenceQueryService:
    def __init__(self, services: IntelligenceServices, repository: Any):
        self.services = services
        self.repository = repository

    def list_releases(
        self,
        since: str | None,
        limit: int,
        workspace_id: str | None = None,
        *,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        del workspace_id
        current = now or datetime.now(UTC)
        parsed_since = parse_datetime(since) if since else None
        page = self.services.releases.list_changes(
            since=parsed_since or current - timedelta(days=7),
            limit=min(max(limit, 1), 100),
            now=current,
        )
        return [
            {
                "id": item.release_id,
                "name": item.name,
                "category": item.category,
                "lane": item.lane,
                "lifecycle": item.lifecycle,
                "age": round(item.age_hours, 1),
                "headline": (
                    item.citations[0].url if item.citations else "No citation"
                ),
                "citation_count": len(item.citations),
                "freshness": item.freshness,
                "review": item.review_status,
            }
            for item in page.items
        ]

    def search(
        self,
        query: str,
        *,
        workspace_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        page = self.services.catalog.search(
            query,
            workspace_id=workspace_id,
            limit=min(max(limit, 1), 100),
        )
        return [
            {
                "id": item.release_id,
                "name": item.name,
                "category": item.category.value,
                "lane": item.lane,
                "lifecycle": item.lifecycle.value,
                "ring": (
                    item.workspace_recommendation.ring.value
                    if item.workspace_recommendation
                    and item.workspace_recommendation.ring
                    else (
                        item.public_recommendation.ring.value
                        if item.public_recommendation.ring
                        else None
                    )
                ),
            }
            for item in page.items
        ]

    def explain(
        self,
        entity_id: str,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        release = self.services.releases.get(entity_id, now=now)
        recommendation = (
            self.services.deployments.fit(entity_id, workspace_id)
            if workspace_id
            else self.services.catalog.search(
                entity_id,
                limit=1,
            ).items[0].public_recommendation
        )
        return {
            **release.model_dump(mode="json"),
            "recommendation": recommendation.model_dump(mode="json"),
        }

    def compare(
        self,
        entity_ids: list[str],
        workspace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            self.explain(entity_id, workspace_id)
            for entity_id in entity_ids
        ]

    def source_health(self) -> list[dict[str, Any]]:
        return [
            {
                "source_id": item.source_id,
                "consecutive_failures": item.consecutive_failures,
                "last_error": item.last_error,
                "last_success_at": (
                    item.last_success_at.isoformat()
                    if item.last_success_at
                    else None
                ),
                "circuit_open_until": (
                    item.circuit_open_until.isoformat()
                    if item.circuit_open_until
                    else None
                ),
                "items_count": item.items_count,
            }
            for item in self.repository.list_source_health()
        ]

    def review_exceptions(
        self,
        open_only: bool = True,
    ) -> list[dict[str, Any]]:
        return [
            review.model_dump(mode="json")
            for review in self.repository.list_review_exceptions(
                open_only=open_only
            )
        ]

    def lineage_suggestions(self) -> list[dict[str, Any]]:
        from radar.intelligence.lineage import list_suggestions

        return [
            edge.model_dump(mode="json")
            for edge in list_suggestions(self.repository)
        ]
