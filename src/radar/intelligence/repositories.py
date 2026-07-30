"""Repository boundary for canonical intelligence persistence."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from radar.intelligence.contracts import (
    Claim,
    ClaimState,
    CompatibilityAssertion,
    EvidenceLevel,
    EvidenceObservation,
    EvidenceStrength,
    LifecycleState,
    LifecycleTransition,
    ModelCategory,
    ProductFamily,
    Publisher,
    Qualification,
    Release,
    ReleaseLane,
    ReviewException,
    SupportStatus,
)
from radar.intelligence.database import Database
from radar.intelligence.jobs import JobKind, JobLease, JobStatus
from radar.intelligence.schema import (
    ClaimEvidenceRow,
    ClaimRow,
    CompatibilityRow,
    EvidenceRow,
    FamilyRow,
    JobRow,
    LegacyEventRow,
    LifecycleTransitionRow,
    PlatformRow,
    PublisherRow,
    QualificationRow,
    ReleaseRow,
    ReviewExceptionRow,
    SourceHealthRow,
    WorkspaceRow,
)
from radar.intelligence.source_health import SourceHealthState
from radar.intelligence.workspaces import Workspace


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


def _job_from_row(row: JobRow) -> JobLease:
    created_at = _as_utc(row.created_at)
    started_at = _as_utc(row.started_at)
    assert created_at is not None
    assert started_at is not None
    return JobLease(
        id=row.id,
        kind=JobKind(row.kind),
        idempotency_key=row.idempotency_key,
        status=JobStatus(row.status),
        attempt=row.attempt,
        leased_until=_as_utc(row.leased_until),
        created_at=created_at,
        started_at=started_at,
        completed_at=_as_utc(row.completed_at),
        result=row.result,
        error=row.error,
    )


def _review_from_row(row: ReviewExceptionRow) -> ReviewException:
    opened_at = _as_utc(row.opened_at)
    assert opened_at is not None
    return ReviewException(
        id=row.id,
        subject_id=row.subject_id,
        code=row.code,
        message=row.message,
        evidence_ids=row.evidence_ids,
        opened_at=opened_at,
        resolved_at=_as_utc(row.resolved_at),
    )


def _source_health_from_row(row: SourceHealthRow) -> SourceHealthState:
    return SourceHealthState(
        source_id=row.source_id,
        consecutive_failures=row.consecutive_failures,
        last_error=row.last_error,
        last_failure_at=_as_utc(row.last_failure_at),
        last_success_at=_as_utc(row.last_success_at),
        latency_ms=row.latency_ms,
        items_count=row.items_count,
        circuit_open_until=_as_utc(row.circuit_open_until),
    )


def _compatibility_from_row(row: CompatibilityRow) -> CompatibilityAssertion:
    return CompatibilityAssertion(
        id=row.id,
        release_id=row.release_id,
        platform_id=row.platform_id,
        platform_version=row.platform_version,
        feature=row.feature,
        support=SupportStatus(row.support),
        evidence_level=EvidenceLevel(row.evidence_level),
        evidence_ids=row.evidence_ids,
        hardware_scope=row.hardware_scope,
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

    def list_publishers(self) -> list[Publisher]:
        with self.database.session() as session:
            rows = list(
                session.scalars(select(PublisherRow).order_by(PublisherRow.id))
            )
            return [
                Publisher(
                    id=row.id,
                    name=row.name,
                    official_domains=row.official_domains,
                    official_accounts=row.official_accounts,
                    aliases=row.aliases,
                )
                for row in rows
            ]

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

    def list_families_for_publisher(
        self,
        publisher_id: str,
    ) -> list[ProductFamily]:
        with self.database.session() as session:
            rows = list(
                session.scalars(
                    select(FamilyRow)
                    .where(FamilyRow.publisher_id == publisher_id)
                    .order_by(FamilyRow.id)
                )
            )
            return [
                ProductFamily(
                    id=row.id,
                    publisher_id=row.publisher_id,
                    name=row.name,
                    aliases=row.aliases,
                )
                for row in rows
            ]

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

    def list_releases_for_publisher(self, publisher_id: str) -> list[Release]:
        with self.database.session() as session:
            rows = list(
                session.scalars(
                    select(ReleaseRow)
                    .where(ReleaseRow.publisher_id == publisher_id)
                    .order_by(ReleaseRow.id)
                )
            )
            return [self._release_from_row(row) for row in rows]

    def get_release_required(self, release_id: str) -> Release:
        release = self.get_release(release_id)
        if release is None:
            raise RepositoryConflict(f"Unknown release: {release_id}")
        return release

    def set_release_lifecycle(
        self,
        release_id: str,
        lifecycle: LifecycleState,
    ) -> None:
        with self.database.session() as session:
            row = session.get(ReleaseRow, release_id)
            if row is None:
                raise RepositoryConflict(f"Unknown release: {release_id}")
            row.lifecycle = lifecycle.value

    def append_lifecycle_transition(
        self,
        transition: LifecycleTransition,
    ) -> None:
        identity = "|".join(
            (
                transition.release_id,
                transition.from_state.value
                if transition.from_state is not None
                else "",
                transition.to_state.value,
                transition.observed_at.isoformat(),
                transition.reason,
                ",".join(sorted(transition.evidence_ids)),
            )
        )
        transition_id = (
            f"transition:{hashlib.sha256(identity.encode()).hexdigest()}"
        )
        with self.database.session() as session:
            existing = session.get(LifecycleTransitionRow, transition_id)
            if existing is not None:
                return
            session.add(
                LifecycleTransitionRow(
                    id=transition_id,
                    release_id=transition.release_id,
                    from_state=(
                        transition.from_state.value
                        if transition.from_state is not None
                        else None
                    ),
                    to_state=transition.to_state.value,
                    observed_at=transition.observed_at,
                    reason=transition.reason,
                    evidence_ids=transition.evidence_ids,
                )
            )

    def list_lifecycle_transitions(
        self,
        release_id: str,
    ) -> list[LifecycleTransition]:
        with self.database.session() as session:
            rows = list(
                session.scalars(
                    select(LifecycleTransitionRow)
                    .where(
                        LifecycleTransitionRow.release_id == release_id
                    )
                    .order_by(
                        LifecycleTransitionRow.observed_at,
                        LifecycleTransitionRow.id,
                    )
                )
            )
            transitions: list[LifecycleTransition] = []
            for row in rows:
                observed_at = _as_utc(row.observed_at)
                assert observed_at is not None
                transitions.append(
                    LifecycleTransition(
                        release_id=row.release_id,
                        from_state=(
                            LifecycleState(row.from_state)
                            if row.from_state is not None
                            else None
                        ),
                        to_state=LifecycleState(row.to_state),
                        observed_at=observed_at,
                        reason=row.reason,
                        evidence_ids=row.evidence_ids,
                    )
                )
            return transitions

    def open_review_exception(self, review: ReviewException) -> None:
        with self.database.session() as session:
            existing = session.get(ReviewExceptionRow, review.id)
            if existing is not None:
                current = _review_from_row(existing)
                if current != review:
                    raise RepositoryConflict(
                        f"Review exception id changed: {review.id}"
                    )
                return
            session.add(
                ReviewExceptionRow(
                    id=review.id,
                    subject_id=review.subject_id,
                    code=review.code,
                    message=review.message,
                    evidence_ids=review.evidence_ids,
                    opened_at=review.opened_at,
                    resolved_at=review.resolved_at,
                    resolution=None,
                )
            )

    def get_review_exception(
        self,
        exception_id: str,
    ) -> ReviewException | None:
        with self.database.session() as session:
            row = session.get(ReviewExceptionRow, exception_id)
            return _review_from_row(row) if row is not None else None

    def resolve_review_exception(
        self,
        exception_id: str,
        resolution: str,
        evidence_ids: list[str],
        now: datetime,
    ) -> None:
        with self.database.session() as session:
            row = session.get(ReviewExceptionRow, exception_id)
            if row is None:
                raise RepositoryConflict(
                    f"Unknown review exception: {exception_id}"
                )
            payload = {
                "resolution": resolution,
                "evidence_ids": evidence_ids,
            }
            if row.resolved_at is not None:
                if row.resolution != payload:
                    raise RepositoryConflict(
                        f"Review resolution changed: {exception_id}"
                    )
                return
            row.resolved_at = now
            row.resolution = payload

    def get_review_resolution(
        self,
        exception_id: str,
    ) -> dict[str, Any] | None:
        with self.database.session() as session:
            row = session.get(ReviewExceptionRow, exception_id)
            return row.resolution if row is not None else None

    def list_review_exceptions(
        self,
        *,
        open_only: bool = False,
    ) -> list[ReviewException]:
        with self.database.session() as session:
            statement = select(ReviewExceptionRow)
            if open_only:
                statement = statement.where(
                    ReviewExceptionRow.resolved_at.is_(None)
                )
            rows = list(
                session.scalars(
                    statement.order_by(
                        ReviewExceptionRow.opened_at.desc(),
                        ReviewExceptionRow.id,
                    )
                )
            )
            return [_review_from_row(row) for row in rows]

    def increment_source_failure(
        self,
        source_id: str,
        error: str,
        now: datetime,
    ) -> SourceHealthState:
        with self.database.session() as session:
            row = session.get(SourceHealthRow, source_id)
            if row is None:
                row = SourceHealthRow(
                    source_id=source_id,
                    consecutive_failures=0,
                    last_error=None,
                    last_failure_at=None,
                    last_success_at=None,
                    latency_ms=None,
                    items_count=None,
                    circuit_open_until=None,
                )
                session.add(row)
            row.consecutive_failures += 1
            row.last_error = error
            row.last_failure_at = now
            session.flush()
            return _source_health_from_row(row)

    def open_source_circuit(
        self,
        source_id: str,
        until: datetime,
    ) -> None:
        with self.database.session() as session:
            row = session.get(SourceHealthRow, source_id)
            if row is None:
                raise RepositoryConflict(f"Unknown source health: {source_id}")
            row.circuit_open_until = until

    def record_source_success(
        self,
        source_id: str,
        latency_ms: float,
        items: int,
        now: datetime,
    ) -> SourceHealthState:
        with self.database.session() as session:
            row = session.get(SourceHealthRow, source_id)
            if row is None:
                row = SourceHealthRow(
                    source_id=source_id,
                    consecutive_failures=0,
                    last_error=None,
                    last_failure_at=None,
                    last_success_at=now,
                    latency_ms=latency_ms,
                    items_count=items,
                    circuit_open_until=None,
                )
                session.add(row)
            else:
                row.consecutive_failures = 0
                row.last_error = None
                row.last_success_at = now
                row.latency_ms = latency_ms
                row.items_count = items
                row.circuit_open_until = None
            session.flush()
            return _source_health_from_row(row)

    def get_source_health(
        self,
        source_id: str,
    ) -> SourceHealthState | None:
        with self.database.session() as session:
            row = session.get(SourceHealthRow, source_id)
            return (
                _source_health_from_row(row) if row is not None else None
            )

    def list_source_health(self) -> list[SourceHealthState]:
        with self.database.session() as session:
            rows = list(
                session.scalars(
                    select(SourceHealthRow).order_by(
                        SourceHealthRow.source_id
                    )
                )
            )
            return [_source_health_from_row(row) for row in rows]

    def count_stale_claims(self) -> int:
        with self.database.session() as session:
            return (
                session.scalar(
                    select(func.count())
                    .select_from(ClaimRow)
                    .where(ClaimRow.state == ClaimState.STALE.value)
                )
                or 0
            )

    def upsert_compatibility(
        self,
        assertion: CompatibilityAssertion,
    ) -> bool:
        with self.database.session() as session:
            row = session.get(CompatibilityRow, assertion.id)
            if row is not None:
                if _compatibility_from_row(row) != assertion:
                    raise RepositoryConflict(
                        f"Compatibility id changed: {assertion.id}"
                    )
                return False
            session.add(
                CompatibilityRow(
                    id=assertion.id,
                    release_id=assertion.release_id,
                    platform_id=assertion.platform_id,
                    platform_version=assertion.platform_version,
                    feature=assertion.feature,
                    support=assertion.support.value,
                    evidence_level=assertion.evidence_level.value,
                    evidence_ids=assertion.evidence_ids,
                    hardware_scope=assertion.hardware_scope,
                )
            )
            return True

    def get_compatibility(
        self,
        assertion_id: str,
    ) -> CompatibilityAssertion | None:
        with self.database.session() as session:
            row = session.get(CompatibilityRow, assertion_id)
            return (
                _compatibility_from_row(row) if row is not None else None
            )

    def list_compatibility(
        self,
        release_id: str,
    ) -> list[CompatibilityAssertion]:
        with self.database.session() as session:
            rows = list(
                session.scalars(
                    select(CompatibilityRow)
                    .where(CompatibilityRow.release_id == release_id)
                    .order_by(CompatibilityRow.id)
                )
            )
            return [_compatibility_from_row(row) for row in rows]

    def list_compatibility_for_evidence(
        self,
        evidence_id: str,
    ) -> list[CompatibilityAssertion]:
        return [
            assertion
            for release in self.list_all_releases()
            for assertion in self.list_compatibility(release.id)
            if evidence_id in assertion.evidence_ids
        ]

    def list_all_releases(self) -> list[Release]:
        with self.database.session() as session:
            rows = list(
                session.scalars(select(ReleaseRow).order_by(ReleaseRow.id))
            )
            return [self._release_from_row(row) for row in rows]

    def set_claim_state(
        self,
        claim_id: str,
        state: ClaimState,
    ) -> None:
        with self.database.session() as session:
            row = session.get(ClaimRow, claim_id)
            if row is None:
                raise RepositoryConflict(f"Unknown claim: {claim_id}")
            row.state = state.value

    def save_qualification(
        self,
        qualification: Qualification,
        now: datetime,
    ) -> None:
        payload = qualification.model_dump(mode="json")
        with self.database.session() as session:
            row = session.get(QualificationRow, qualification.release_id)
            if row is None:
                session.add(
                    QualificationRow(
                        **payload,
                        computed_at=now,
                    )
                )
                return
            row.qualified = qualification.qualified
            row.category = qualification.category.value
            row.reasons = qualification.reasons
            row.assumptions = qualification.assumptions
            row.evidence_ids = qualification.evidence_ids
            row.computed_at = now

    def get_qualification(
        self,
        release_id: str,
    ) -> Qualification | None:
        with self.database.session() as session:
            row = session.get(QualificationRow, release_id)
            if row is None:
                return None
            return Qualification(
                release_id=row.release_id,
                qualified=row.qualified,
                category=ModelCategory(row.category),
                reasons=row.reasons,
                assumptions=row.assumptions,
                evidence_ids=row.evidence_ids,
            )

    def create_workspace(self, workspace: Workspace) -> Workspace:
        now = datetime.now(UTC)
        payload = workspace.model_dump(mode="json")
        workspace_id = str(payload.pop("id"))
        schema_version = int(payload.pop("schema_version"))
        with self.database.session() as session:
            if session.get(WorkspaceRow, workspace_id) is not None:
                raise RepositoryConflict(
                    f"Workspace already exists: {workspace_id}"
                )
            session.add(
                WorkspaceRow(
                    id=workspace_id,
                    schema_version=schema_version,
                    payload=payload,
                    created_at=now,
                    updated_at=now,
                )
            )
        return workspace

    def get_workspace(self, workspace_id: str) -> Workspace | None:
        with self.database.session() as session:
            row = session.get(WorkspaceRow, workspace_id)
            if row is None:
                return None
            return Workspace(
                id=row.id,
                schema_version=row.schema_version,
                **row.payload,
            )

    def list_workspaces(self) -> list[Workspace]:
        with self.database.session() as session:
            rows = list(
                session.scalars(select(WorkspaceRow).order_by(WorkspaceRow.id))
            )
            return [
                Workspace(
                    id=row.id,
                    schema_version=row.schema_version,
                    **row.payload,
                )
                for row in rows
            ]

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

    @staticmethod
    def _acquire_job_in_session(
        session: Session,
        *,
        kind: str,
        idempotency_key: str,
        leased_until: datetime,
        now: datetime,
        lock: bool,
    ) -> JobLease | None:
        statement = select(JobRow).where(
            JobRow.idempotency_key == idempotency_key
        )
        if lock:
            statement = statement.with_for_update()
        existing = session.scalar(statement)
        if existing is None:
            digest = hashlib.sha256(idempotency_key.encode()).hexdigest()
            existing = JobRow(
                id=f"job:{digest}",
                kind=kind,
                idempotency_key=idempotency_key,
                status=JobStatus.RUNNING.value,
                attempt=1,
                leased_until=leased_until,
                created_at=now,
                started_at=now,
                completed_at=None,
                result=None,
                error=None,
            )
            session.add(existing)
            session.flush()
            return _job_from_row(existing)
        if existing.kind != kind:
            raise RepositoryConflict(
                f"Job key {idempotency_key} changed kind from "
                f"{existing.kind} to {kind}"
            )
        lease_expiry = _as_utc(existing.leased_until)
        if existing.status == JobStatus.COMPLETED.value:
            return None
        if (
            existing.status == JobStatus.RUNNING.value
            and lease_expiry is not None
            and lease_expiry > now
        ):
            return None
        existing.status = JobStatus.RUNNING.value
        existing.attempt += 1
        existing.leased_until = leased_until
        existing.started_at = now
        existing.completed_at = None
        existing.result = None
        existing.error = None
        session.flush()
        return _job_from_row(existing)

    def acquire_job(
        self,
        *,
        kind: str,
        idempotency_key: str,
        leased_until: datetime,
        now: datetime,
    ) -> JobLease | None:
        if self.database.engine.dialect.name == "sqlite":
            with self.database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                with Session(bind=connection) as session:
                    lease = self._acquire_job_in_session(
                        session,
                        kind=kind,
                        idempotency_key=idempotency_key,
                        leased_until=leased_until,
                        now=now,
                        lock=False,
                    )
                    session.flush()
                    connection.commit()
                    return lease
        try:
            with self.database.session() as session:
                return self._acquire_job_in_session(
                    session,
                    kind=kind,
                    idempotency_key=idempotency_key,
                    leased_until=leased_until,
                    now=now,
                    lock=True,
                )
        except IntegrityError:
            return None

    def complete_job(
        self,
        job_id: str,
        result: dict[str, Any],
        now: datetime,
    ) -> None:
        with self.database.session() as session:
            row = session.get(JobRow, job_id)
            if row is None:
                raise RepositoryConflict(f"Unknown job: {job_id}")
            if row.status == JobStatus.COMPLETED.value:
                if row.result != result:
                    raise RepositoryConflict(f"Completed job changed: {job_id}")
                return
            row.status = JobStatus.COMPLETED.value
            row.leased_until = None
            row.completed_at = now
            row.result = result
            row.error = None

    def fail_job(self, job_id: str, error: str, now: datetime) -> None:
        with self.database.session() as session:
            row = session.get(JobRow, job_id)
            if row is None:
                raise RepositoryConflict(f"Unknown job: {job_id}")
            if row.status == JobStatus.COMPLETED.value:
                raise RepositoryConflict(f"Completed job cannot fail: {job_id}")
            if row.status == JobStatus.FAILED.value and row.error == error:
                return
            row.status = JobStatus.FAILED.value
            row.leased_until = None
            row.completed_at = now
            row.result = None
            row.error = error

    def get_job(self, job_id: str) -> JobLease | None:
        with self.database.session() as session:
            row = session.get(JobRow, job_id)
            return _job_from_row(row) if row is not None else None
