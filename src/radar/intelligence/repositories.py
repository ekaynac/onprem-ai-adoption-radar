"""Repository boundary for canonical intelligence persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from radar.intelligence.contracts import (
    Claim,
    ClaimState,
    EvidenceObservation,
    EvidenceStrength,
    LifecycleState,
    ModelCategory,
    ProductFamily,
    Publisher,
    Release,
    ReleaseLane,
)
from radar.intelligence.database import Database
from radar.intelligence.schema import (
    ClaimEvidenceRow,
    ClaimRow,
    EvidenceRow,
    FamilyRow,
    LegacyEventRow,
    PlatformRow,
    PublisherRow,
    ReleaseRow,
)


class RepositoryConflict(ValueError):
    """An append-only ID was reused for different content."""


class IntelligenceRepository(Protocol):
    def append_evidence(self, evidence: EvidenceObservation) -> None: ...

    def get_evidence(self, evidence_id: str) -> EvidenceObservation | None: ...

    def count_evidence(self) -> int: ...

    def append_claim(self, claim: Claim) -> None: ...

    def get_claim(self, claim_id: str) -> Claim | None: ...


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _evidence_from_row(row: EvidenceRow) -> EvidenceObservation:
    retrieved_at = _as_utc(row.retrieved_at)
    assert retrieved_at is not None
    return EvidenceObservation(
        id=row.id,
        source_url=row.source_url,
        strength=EvidenceStrength(row.strength),
        retrieved_at=retrieved_at,
        checksum=row.checksum,
        extractor_version=row.extractor_version,
        raw_snapshot_path=row.raw_snapshot_path,
    )


def _claim_from_session(session: Session, row: ClaimRow) -> Claim:
    evidence_ids = list(
        session.scalars(
            select(ClaimEvidenceRow.evidence_id)
            .where(ClaimEvidenceRow.claim_id == row.id)
            .order_by(ClaimEvidenceRow.evidence_id)
        )
    )
    observed_at = _as_utc(row.observed_at)
    assert observed_at is not None
    return Claim(
        id=row.id,
        subject_id=row.subject_id,
        predicate=row.predicate,
        value=row.value,
        unit=row.unit,
        state=ClaimState(row.state),
        observed_at=observed_at,
        valid_from=_as_utc(row.valid_from),
        valid_to=_as_utc(row.valid_to),
        supersedes_claim_id=row.supersedes_claim_id,
        evidence_ids=evidence_ids,
    )


class SqlAlchemyIntelligenceRepository:
    def __init__(self, database: Database):
        self.database = database

    def append_evidence(self, evidence: EvidenceObservation) -> None:
        with self.database.session() as session:
            existing = session.get(EvidenceRow, evidence.id)
            if existing is not None:
                if _evidence_from_row(existing) != evidence:
                    raise RepositoryConflict(f"Evidence id changed: {evidence.id}")
                return
            session.add(
                EvidenceRow(
                    id=evidence.id,
                    source_url=evidence.source_url,
                    strength=evidence.strength.value,
                    retrieved_at=evidence.retrieved_at,
                    checksum=evidence.checksum,
                    extractor_version=evidence.extractor_version,
                    raw_snapshot_path=evidence.raw_snapshot_path,
                )
            )

    def get_evidence(self, evidence_id: str) -> EvidenceObservation | None:
        with self.database.session() as session:
            row = session.get(EvidenceRow, evidence_id)
            return _evidence_from_row(row) if row is not None else None

    def count_evidence(self) -> int:
        with self.database.session() as session:
            return session.scalar(select(func.count()).select_from(EvidenceRow)) or 0

    def append_claim(self, claim: Claim) -> None:
        with self.database.session() as session:
            existing = session.get(ClaimRow, claim.id)
            if existing is not None:
                if _claim_from_session(session, existing) != claim:
                    raise RepositoryConflict(f"Claim id changed: {claim.id}")
                return
            missing = [
                evidence_id
                for evidence_id in claim.evidence_ids
                if session.get(EvidenceRow, evidence_id) is None
            ]
            if missing:
                raise RepositoryConflict(
                    f"Claim {claim.id} references missing evidence: {', '.join(missing)}"
                )
            claim_row = ClaimRow(
                id=claim.id,
                subject_id=claim.subject_id,
                predicate=claim.predicate,
                value=claim.value,
                unit=claim.unit,
                state=claim.state.value,
                observed_at=claim.observed_at,
                valid_from=claim.valid_from,
                valid_to=claim.valid_to,
                supersedes_claim_id=claim.supersedes_claim_id,
            )
            session.add(claim_row)
            session.flush()
            session.add_all(
                ClaimEvidenceRow(claim_id=claim.id, evidence_id=evidence_id)
                for evidence_id in sorted(claim.evidence_ids)
            )

    def get_claim(self, claim_id: str) -> Claim | None:
        with self.database.session() as session:
            row = session.get(ClaimRow, claim_id)
            return _claim_from_session(session, row) if row is not None else None

    def list_claims_for_subject(self, subject_id: str) -> list[Claim]:
        with self.database.session() as session:
            rows = list(
                session.scalars(
                    select(ClaimRow)
                    .where(ClaimRow.subject_id == subject_id)
                    .order_by(ClaimRow.predicate, ClaimRow.observed_at, ClaimRow.id)
                )
            )
            return [_claim_from_session(session, row) for row in rows]

    def upsert_publisher(self, publisher: Publisher) -> bool:
        with self.database.session() as session:
            existing = session.get(PublisherRow, publisher.id)
            if existing is not None:
                current = Publisher(
                    id=existing.id,
                    name=existing.name,
                    official_domains=existing.official_domains,
                    official_accounts=existing.official_accounts,
                    aliases=existing.aliases,
                )
                if current != publisher:
                    raise RepositoryConflict(f"Publisher id changed: {publisher.id}")
                return False
            session.add(PublisherRow(**publisher.model_dump(mode="json")))
            return True

    def upsert_family(self, family: ProductFamily) -> bool:
        with self.database.session() as session:
            existing = session.get(FamilyRow, family.id)
            if existing is not None:
                current = ProductFamily(
                    id=existing.id,
                    publisher_id=existing.publisher_id,
                    name=existing.name,
                    aliases=existing.aliases,
                )
                if current != family:
                    raise RepositoryConflict(f"Family id changed: {family.id}")
                return False
            session.add(FamilyRow(**family.model_dump(mode="json")))
            return True

    def upsert_release(self, release: Release) -> bool:
        with self.database.session() as session:
            existing = session.get(ReleaseRow, release.id)
            if existing is not None:
                current = self._release_from_row(existing)
                if current != release:
                    raise RepositoryConflict(f"Release id changed: {release.id}")
                return False
            session.add(
                ReleaseRow(
                    id=release.id,
                    family_id=release.family_id,
                    publisher_id=release.publisher_id,
                    name=release.name,
                    category=release.category.value,
                    lane=release.lane.value,
                    lifecycle=release.lifecycle.value,
                    first_observed_at=release.first_observed_at,
                    discovery_evidence_strength=(
                        release.discovery_evidence_strength.value
                    ),
                )
            )
            return True

    @staticmethod
    def _release_from_row(row: ReleaseRow) -> Release:
        first_observed_at = _as_utc(row.first_observed_at)
        assert first_observed_at is not None
        return Release(
            id=row.id,
            family_id=row.family_id,
            publisher_id=row.publisher_id,
            name=row.name,
            category=ModelCategory(row.category),
            lane=ReleaseLane(row.lane),
            lifecycle=LifecycleState(row.lifecycle),
            first_observed_at=first_observed_at,
            discovery_evidence_strength=EvidenceStrength(
                row.discovery_evidence_strength
            ),
        )

    def get_release(self, release_id: str) -> Release | None:
        with self.database.session() as session:
            row = session.get(ReleaseRow, release_id)
            return self._release_from_row(row) if row is not None else None

    def count_releases(self) -> int:
        with self.database.session() as session:
            return session.scalar(select(func.count()).select_from(ReleaseRow)) or 0

    def import_platform(
        self,
        *,
        platform_id: str,
        name: str,
        repo_url: str,
        verified_at: str,
        payload: dict[str, object],
    ) -> bool:
        with self.database.session() as session:
            existing = session.get(PlatformRow, platform_id)
            if existing is not None:
                if (
                    existing.name != name
                    or existing.repo_url != repo_url
                    or existing.verified_at != verified_at
                    or existing.payload != payload
                ):
                    raise RepositoryConflict(f"Platform id changed: {platform_id}")
                return False
            session.add(
                PlatformRow(
                    id=platform_id,
                    name=name,
                    repo_url=repo_url,
                    verified_at=verified_at,
                    payload=payload,
                )
            )
            return True

    def count_platforms(self) -> int:
        with self.database.session() as session:
            return session.scalar(select(func.count()).select_from(PlatformRow)) or 0

    def append_legacy_event(
        self,
        *,
        event_id: str,
        kind: str,
        subject_id: str,
        observed_at: datetime,
        payload: dict[str, object],
    ) -> bool:
        with self.database.session() as session:
            existing = session.get(LegacyEventRow, event_id)
            if existing is not None:
                if (
                    existing.kind != kind
                    or existing.subject_id != subject_id
                    or _as_utc(existing.observed_at) != observed_at
                    or existing.payload != payload
                ):
                    raise RepositoryConflict(f"Legacy event id changed: {event_id}")
                return False
            session.add(
                LegacyEventRow(
                    id=event_id,
                    kind=kind,
                    subject_id=subject_id,
                    observed_at=observed_at,
                    payload=payload,
                )
            )
            return True

    def count_legacy_events(self, kind: str | None = None) -> int:
        with self.database.session() as session:
            statement = select(func.count()).select_from(LegacyEventRow)
            if kind is not None:
                statement = statement.where(LegacyEventRow.kind == kind)
            return session.scalar(statement) or 0
