"""Stable catalog search projections."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import Field

from radar.intelligence.contracts import (
    Claim,
    CompatibilityAssertion,
    EvidenceObservation,
    EvidenceStrength,
    FrozenModel,
    LifecycleState,
    ModelCategory,
    Qualification,
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


class ClaimCitation(FrozenModel):
    evidence_id: str
    url: str
    label: str
    strength: EvidenceStrength


class ClaimDetail(FrozenModel):
    predicate: str
    state: str
    value: Any | None = None
    unit: str | None = None
    reason: str | None = None
    observed_at: str | None = None
    effective_range: str | None = None
    citations: list[ClaimCitation] = Field(default_factory=list)


class CatalogDetail(FrozenModel):
    release: CatalogItem
    claims: list[ClaimDetail]
    compatibility: list[CompatibilityAssertion]
    qualification: Qualification | None = None


class CatalogRepository(Protocol):
    def list_all_releases(self) -> list[Release]: ...

    def get_release(self, release_id: str) -> Release | None: ...

    def list_claims_for_subject(self, subject_id: str) -> list[Claim]: ...

    def get_evidence(
        self,
        evidence_id: str,
    ) -> EvidenceObservation | None: ...

    def list_compatibility(
        self,
        release_id: str,
    ) -> list[CompatibilityAssertion]: ...

    def get_qualification(self, release_id: str) -> Qualification | None: ...


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

    def get(
        self,
        release_id: str,
        *,
        workspace_id: str | None = None,
    ) -> CatalogItem:
        release = self.repository.get_release(release_id)
        if release is None:
            raise KeyError(f"Unknown release: {release_id}")
        return self._project(release, [], workspace_id)

    def detail(
        self,
        release_id: str,
        *,
        workspace_id: str | None = None,
    ) -> CatalogDetail:
        release = self.get(release_id, workspace_id=workspace_id)
        claims = self.repository.list_claims_for_subject(release_id)
        details = [self._claim_detail(claim) for claim in claims]
        present = {claim.predicate for claim in claims}
        for predicate in _expected_claims(release.category):
            if predicate not in present:
                details.append(
                    ClaimDetail(
                        predicate=predicate,
                        state="unknown",
                        reason="No official value found",
                    )
                )
        details.sort(key=lambda item: item.predicate)
        return CatalogDetail(
            release=release,
            claims=details,
            compatibility=self.repository.list_compatibility(release_id),
            qualification=self.repository.get_qualification(release_id),
        )

    def _claim_detail(self, claim: Claim) -> ClaimDetail:
        citations: list[ClaimCitation] = []
        for evidence_id in claim.evidence_ids:
            evidence = self.repository.get_evidence(evidence_id)
            if evidence is None:
                continue
            citations.append(
                ClaimCitation(
                    evidence_id=evidence.id,
                    url=evidence.source_url,
                    label=(
                        "Official source"
                        if evidence.strength.value.startswith("official_")
                        else "Evidence source"
                    ),
                    strength=evidence.strength,
                )
            )
        return ClaimDetail(
            predicate=claim.predicate,
            state=claim.state.value,
            value=claim.value,
            unit=claim.unit,
            observed_at=claim.observed_at.isoformat(),
            effective_range=(
                " – ".join(
                    value
                    for value in (
                        claim.valid_from.isoformat() if claim.valid_from else None,
                        claim.valid_to.isoformat() if claim.valid_to else None,
                    )
                    if value
                )
                or None
            ),
            citations=citations,
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


def _expected_claims(category: ModelCategory) -> tuple[str, ...]:
    common = ("architecture", "context_length", "license", "params_total")
    category_specific = {
        ModelCategory.TEXT_REASONING: ("tool_calling",),
        ModelCategory.MULTIMODAL: ("modalities",),
        ModelCategory.EMBEDDING_RERANKING: ("embedding_dimensions",),
        ModelCategory.SPEECH_AUDIO: ("languages",),
        ModelCategory.IMAGE_VIDEO: ("max_resolution",),
        ModelCategory.VISION_DOCUMENT: ("document_formats",),
    }
    return (*common, *category_specific[category])
