"""Stable catalog search projections."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
    lineage: dict[str, Any] | None = None
    is_official: bool | None = None


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

    def latest_claim_values(
        self,
        subject_ids: list[str],
        predicates: set[str],
    ) -> dict[str, dict[str, Any]]: ...


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
        lane: str | None = None,
        publisher: str | None = None,
        license: str | None = None,
        hardware: str | None = None,
        modality: str | None = None,
        platform: str | None = None,
        freshness: str | None = None,
        now: datetime | None = None,
        workspace_id: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[CatalogItem]:
        tokens = [
            token
            for token in query.casefold().replace("-", " ").split()
            if token
        ]
        releases = self.repository.list_all_releases()
        metadata = self.repository.latest_claim_values(
            [release.id for release in releases],
            {
                "hardware_tier",
                "last_modified",
                "library_name",
                "license",
                "modality",
                "pipeline_tag",
            },
        )
        current = now or datetime.now(UTC)
        matches: list[tuple[int, Release, list[str]]] = []
        for release in releases:
            if category is not None and release.category is not category:
                continue
            if lifecycle is not None and release.lifecycle is not lifecycle:
                continue
            values = metadata.get(release.id, {})
            if lane is not None and release.lane.value != lane:
                continue
            if publisher is not None and release.publisher_id != publisher:
                continue
            if license is not None and values.get("license") != license:
                continue
            if hardware is not None and values.get("hardware_tier") != hardware:
                continue
            release_modality = (
                values.get("modality")
                or values.get("pipeline_tag")
                or release.category.value
            )
            if modality is not None and release_modality != modality:
                continue
            if platform is not None and values.get("library_name") != platform:
                continue
            if freshness is not None:
                timestamp = _claim_datetime(values.get("last_modified")) or release.first_observed_at
                is_fresh = current - timestamp <= timedelta(days=7)
                if (freshness == "fresh") != is_fresh:
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

    def facets(self) -> dict[str, list[str]]:
        releases = self.repository.list_all_releases()
        metadata = self.repository.latest_claim_values(
            [release.id for release in releases],
            {
                "hardware_tier",
                "library_name",
                "license",
                "modality",
                "pipeline_tag",
            },
        )

        def values(predicate: str) -> list[str]:
            return sorted(
                {
                    str(claims[predicate])
                    for claims in metadata.values()
                    if claims.get(predicate) not in {None, ""}
                },
                key=str.casefold,
            )

        modalities = {
            release.category.value for release in releases
        } | {
            str(claims.get("modality") or claims.get("pipeline_tag"))
            for claims in metadata.values()
            if claims.get("modality") or claims.get("pipeline_tag")
        }
        return {
            "publisher": sorted({release.publisher_id for release in releases}, key=str.casefold),
            "license": values("license"),
            "hardware": values("hardware_tier"),
            "modality": sorted(modalities, key=str.casefold),
            "platform": values("library_name"),
            "freshness": ["fresh", "stale"] if releases else [],
        }

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
            lineage=self._lineage(release.id),
            is_official=not release.publisher_id.startswith(
                "publisher:provisional:"
            ),
        )

    def _lineage(self, release_id: str) -> dict[str, Any] | None:
        lister = getattr(self.repository, "list_lineage_for_child", None)
        if lister is None:
            return None
        edges = lister(release_id)
        if not edges:
            return None
        primary = max(
            edges,
            key=lambda edge: (
                edge.confidence,
                edge.parent_release_id or "",
                edge.id,
            ),
        )
        return {
            "base_release": primary.parent_release_id,
            "relation": primary.relation.value,
            "root_release": primary.root_release_id,
        }


def _claim_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or UTC)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC)


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
