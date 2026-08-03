"""Release-stream and detail projections with citations."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import Field

from radar.intelligence.contracts import (
    Claim,
    EvidenceObservation,
    EvidenceStrength,
    FrozenModel,
    Release,
    ReviewException,
)
from radar.intelligence.freshness import FreshnessService
from radar.intelligence.services import Page


_CONFIDENCE = {
    EvidenceStrength.OFFICIAL_ARTIFACT: 1.0,
    EvidenceStrength.OFFICIAL_DOCUMENTATION: 0.95,
    EvidenceStrength.OFFICIAL_REPOSITORY: 0.95,
    EvidenceStrength.OFFICIAL_ANNOUNCEMENT: 0.9,
    EvidenceStrength.TRUSTED_REGISTRY: 0.8,
    EvidenceStrength.BENCHMARK_MAINTAINER: 0.7,
    EvidenceStrength.AGGREGATOR: 0.35,
    EvidenceStrength.COMMUNITY: 0.2,
}


class Citation(FrozenModel):
    evidence_id: str
    url: str
    strength: EvidenceStrength
    retrieved_at: datetime


class ReleaseChange(FrozenModel):
    release_id: str
    name: str
    lifecycle: str
    lane: str
    category: str
    first_observed_at: datetime
    released_at: datetime | None = None
    age_hours: float
    freshness: str
    confidence: float
    review_status: str
    citations: list[Citation] = Field(default_factory=list)


class ReleaseRepository(Protocol):
    def list_all_releases(self) -> list[Release]: ...

    def get_release(self, release_id: str) -> Release | None: ...

    def list_claims_for_subject(self, subject_id: str) -> list[Claim]: ...

    def get_evidence(
        self,
        evidence_id: str,
    ) -> EvidenceObservation | None: ...

    def list_review_exceptions(
        self,
        *,
        open_only: bool = False,
    ) -> list[ReviewException]: ...


class ReleaseService:
    def __init__(self, repository: ReleaseRepository):
        self.repository = repository
        self.freshness = FreshnessService()

    def list_changes(
        self,
        *,
        since: datetime,
        limit: int = 50,
        now: datetime,
    ) -> Page[ReleaseChange]:
        rows = [
            release
            for release in self.repository.list_all_releases()
            if release.first_observed_at >= since
        ]
        rows.sort(
            key=lambda release: (
                -release.first_observed_at.timestamp(),
                release.id,
            )
        )
        page_size = min(max(limit, 1), 100)
        return Page(
            items=[
                self._project(release, now)
                for release in rows[:page_size]
            ],
            next_cursor=(
                rows[page_size - 1].id
                if len(rows) > page_size
                else None
            ),
        )

    def get(self, release_id: str, *, now: datetime) -> ReleaseChange:
        release = self.repository.get_release(release_id)
        if release is None:
            raise KeyError(f"Unknown release: {release_id}")
        return self._project(release, now)

    def _project(
        self,
        release: Release,
        now: datetime,
    ) -> ReleaseChange:
        evidence = self._evidence_for(release.id)
        latest = max(
            (item.retrieved_at for item in evidence),
            default=release.first_observed_at,
        )
        freshness = self.freshness.status(
            "release_identity_new",
            latest,
            now,
        )
        open_reviews = {
            review.subject_id
            for review in self.repository.list_review_exceptions(
                open_only=True
            )
        }
        return ReleaseChange(
            release_id=release.id,
            name=release.name,
            lifecycle=release.lifecycle.value,
            lane=release.lane.value,
            category=release.category.value,
            first_observed_at=release.first_observed_at,
            age_hours=max(
                0.0,
                (now - release.first_observed_at).total_seconds() / 3600,
            ),
            freshness=freshness.value,
            confidence=max(
                (_CONFIDENCE[item.strength] for item in evidence),
                default=_CONFIDENCE[
                    release.discovery_evidence_strength
                ],
            ),
            review_status=(
                "open" if release.id in open_reviews else "clear"
            ),
            citations=[
                Citation(
                    evidence_id=item.id,
                    url=item.source_url,
                    strength=item.strength,
                    retrieved_at=item.retrieved_at,
                )
                for item in evidence
            ],
        )

    def _evidence_for(
        self,
        release_id: str,
    ) -> list[EvidenceObservation]:
        evidence: dict[str, EvidenceObservation] = {}
        for claim in self.repository.list_claims_for_subject(release_id):
            for evidence_id in claim.evidence_ids:
                item = self.repository.get_evidence(evidence_id)
                if item is not None:
                    evidence[item.id] = item
        return sorted(
            evidence.values(),
            key=lambda item: (-item.retrieved_at.timestamp(), item.id),
        )
