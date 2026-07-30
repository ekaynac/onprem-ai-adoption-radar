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
)
from radar.intelligence.database import Database
from radar.intelligence.schema import ClaimEvidenceRow, ClaimRow, EvidenceRow


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
