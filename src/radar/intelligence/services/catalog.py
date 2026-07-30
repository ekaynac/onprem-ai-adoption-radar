"""Stable catalog search projections."""

from __future__ import annotations

from typing import Protocol

from pydantic import Field

from radar.intelligence.contracts import (
    FrozenModel,
    LifecycleState,
    ModelCategory,
    Release,
)
from radar.intelligence.recommendations import (
    RecommendationService,
    RecommendationView,
)
from radar.intelligence.services import Page


_LIFECYCLE_RANK = {
    LifecycleState.DETECTED: 1,
    LifecycleState.VERIFIED: 2,
    LifecycleState.QUALIFIED: 3,
    LifecycleState.RECOMMENDED: 4,
}


class CatalogItem(FrozenModel):
    release_id: str
    name: str
    category: ModelCategory
    lane: str
    lifecycle: LifecycleState
    first_observed_at: str
    public_recommendation: RecommendationView
    workspace_recommendation: RecommendationView | None = None
    matched_terms: list[str] = Field(default_factory=list)


class CatalogRepository(Protocol):
    def list_all_releases(self) -> list[Release]: ...


class CatalogService:
    def __init__(
        self,
        repository: CatalogRepository,
        recommendations: RecommendationService,
    ):
        self.repository = repository
        self.recommendations = recommendations

    def search(
        self,
        query: str,
        *,
        category: ModelCategory | None = None,
        lifecycle: LifecycleState | None = None,
        workspace_id: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[CatalogItem]:
        tokens = [
            token
            for token in query.casefold().replace("-", " ").split()
            if token
        ]
        matches: list[tuple[int, Release, list[str]]] = []
        for release in self.repository.list_all_releases():
            if category is not None and release.category is not category:
                continue
            if lifecycle is not None and release.lifecycle is not lifecycle:
                continue
            haystack = " ".join(
                (
                    release.id,
                    release.name,
                    release.category.value,
                    release.lane.value,
                    release.lifecycle.value,
                )
            ).casefold()
            matched = [token for token in tokens if token in haystack]
            if tokens and len(matched) != len(tokens):
                continue
            matches.append((len(matched), release, matched))
        matches.sort(
            key=lambda item: (
                -item[0],
                -_LIFECYCLE_RANK[item[1].lifecycle],
                -item[1].first_observed_at.timestamp(),
                item[1].id,
            )
        )
        if cursor is not None:
            matches = [
                item
                for item in matches
                if _cursor_for(item[1]) > cursor
            ]
        page_size = min(max(limit, 1), 100)
        selected = matches[:page_size]
        next_cursor = (
            _cursor_for(selected[-1][1])
            if len(matches) > page_size
            else None
        )
        return Page(
            items=[
                self._project(release, matched, workspace_id)
                for _score, release, matched in selected
            ],
            next_cursor=next_cursor,
        )

    def _project(
        self,
        release: Release,
        matched_terms: list[str],
        workspace_id: str | None,
    ) -> CatalogItem:
        return CatalogItem(
            release_id=release.id,
            name=release.name,
            category=release.category,
            lane=release.lane.value,
            lifecycle=release.lifecycle,
            first_observed_at=release.first_observed_at.isoformat(),
            public_recommendation=self.recommendations.public(release.id),
            workspace_recommendation=(
                self.recommendations.for_workspace(
                    release.id,
                    workspace_id,
                )
                if workspace_id is not None
                else None
            ),
            matched_terms=matched_terms,
        )


def _cursor_for(release: Release) -> str:
    return release.id
