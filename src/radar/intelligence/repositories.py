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
    LineageEdge,
    LineageRelation,
    LineageReviewStatus,
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
from radar.intelligence.events import IntelligenceEvent, WebhookAttempt
from radar.intelligence.jobs import JobKind, JobLease, JobStatus
from radar.intelligence.schema import (
    ClaimEvidenceRow,
    ClaimRow,
    CompatibilityRow,
    EvidenceRow,
    FamilyRow,
    IntelligenceEventRow,
    JobRow,
    LegacyEventRow,
    LifecycleTransitionRow,
    LineageEdgeRow,
    PlatformRow,
    PublisherRow,
    QualificationRow,
    ReleaseRow,
    ReviewExceptionRow,
    SourceHealthRow,
    WebhookAttemptRow,
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


def _lineage_from_row(row: LineageEdgeRow) -> LineageEdge:
    return LineageEdge(
        id=row.id,
        child_release_id=row.child_release_id,
        parent_external_ref=row.parent_external_ref,
        parent_release_id=row.parent_release_id,
        root_release_id=row.root_release_id,
        relation=LineageRelation(row.relation),
        declared=row.declared,
        confidence=row.confidence,
        evidence_ids=list(row.evidence_ids),
        extractor_version=row.extractor_version,
        review_status=LineageReviewStatus(row.review_status),
        observed_at=_as_utc(row.observed_at) or row.observed_at,
    )


def _event_from_row(row: IntelligenceEventRow) -> IntelligenceEvent:
    occurred_at = _as_utc(row.occurred_at)
    assert occurred_at is not None
    return IntelligenceEvent(
        schema_version=row.schema_version,
        id=row.id,
        type=row.type,
        occurred_at=occurred_at,
        subject_id=row.subject_id,
        workspace_id=row.workspace_id,
        data=row.data,
        evidence_ids=row.evidence_ids,
    )


def _webhook_attempt_from_row(row: WebhookAttemptRow) -> WebhookAttempt:
    attempted_at = _as_utc(row.attempted_at)
    assert attempted_at is not None
    return WebhookAttempt(
        id=row.id,
        event_id=row.event_id,
        destination=row.destination,
        attempt=row.attempt,
        signature=row.signature,
        http_status=row.http_status,
        response_excerpt=row.response_excerpt,
        next_retry_at=_as_utc(row.next_retry_at),
        terminal=row.terminal,
        attempted_at=attempted_at,
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

    def append_event(self, event: IntelligenceEvent) -> bool:
        with self.database.session() as session:
            existing = session.get(IntelligenceEventRow, event.id)
            if existing is not None:
                if _event_from_row(existing) != event:
                    raise RepositoryConflict(f"Event id changed: {event.id}")
                return False
            session.add(
                IntelligenceEventRow(
                    **event.model_dump(mode="python"),
                )
            )
            return True

    def get_event(self, event_id: str) -> IntelligenceEvent | None:
        with self.database.session() as session:
            row = session.get(IntelligenceEventRow, event_id)
            return _event_from_row(row) if row is not None else None

    def list_events(
        self,
        *,
        limit: int = 100,
        public_only: bool = False,
    ) -> list[IntelligenceEvent]:
        with self.database.session() as session:
            statement = select(IntelligenceEventRow)
            if public_only:
                statement = statement.where(
                    IntelligenceEventRow.workspace_id.is_(None)
                )
            rows = list(
                session.scalars(
                    statement.order_by(
                        IntelligenceEventRow.occurred_at.desc(),
                        IntelligenceEventRow.id,
                    ).limit(limit)
                )
            )
            return [_event_from_row(row) for row in rows]

    def record_webhook_attempt(self, attempt: WebhookAttempt) -> bool:
        with self.database.session() as session:
            existing = session.get(WebhookAttemptRow, attempt.id)
            if existing is not None:
                if _webhook_attempt_from_row(existing) != attempt:
                    raise RepositoryConflict(
                        f"Webhook attempt id changed: {attempt.id}"
                    )
                return False
            session.add(
                WebhookAttemptRow(**attempt.model_dump(mode="python"))
            )
            return True

    def list_webhook_attempts(self, event_id: str) -> list[WebhookAttempt]:
        with self.database.session() as session:
            rows = list(
                session.scalars(
                    select(WebhookAttemptRow)
                    .where(WebhookAttemptRow.event_id == event_id)
                    .order_by(
                        WebhookAttemptRow.attempt,
                        WebhookAttemptRow.destination,
                    )
                )
            )
            return [_webhook_attempt_from_row(row) for row in rows]

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

    def latest_values_for_predicate(self, predicate: str) -> dict[str, Any]:
        """Latest value per subject for ONE predicate (unbounded subjects).

        Exists for registry-wide lookup predicates (e.g. repo aliases)
        whose subjects are not releases and cannot be enumerated upfront.
        """
        with self.database.session() as session:
            rows = session.execute(
                select(
                    ClaimRow.subject_id,
                    ClaimRow.value,
                    ClaimRow.observed_at,
                    ClaimRow.id,
                )
                .where(ClaimRow.predicate == predicate)
                .order_by(
                    ClaimRow.subject_id,
                    ClaimRow.observed_at,
                    ClaimRow.id,
                )
            ).all()
        values: dict[str, Any] = {}
        for subject_id, value, _observed_at, _claim_id in rows:
            values[subject_id] = value  # ordered ascending: last wins
        return values

    def latest_claim_values(
        self,
        subject_ids: list[str],
        predicates: set[str],
    ) -> dict[str, dict[str, Any]]:
        """Return latest values for selected claims in one bounded query."""
        if not subject_ids or not predicates:
            return {}
        with self.database.session() as session:
            rows = list(
                session.execute(
                    select(
                        ClaimRow.subject_id,
                        ClaimRow.predicate,
                        ClaimRow.value,
                        ClaimRow.observed_at,
                        ClaimRow.id,
                    )
                    .where(ClaimRow.subject_id.in_(subject_ids))
                    .where(ClaimRow.predicate.in_(predicates))
                    .order_by(
                        ClaimRow.subject_id,
                        ClaimRow.predicate,
                        ClaimRow.observed_at,
                        ClaimRow.id,
                    )
                )
            )
        values: dict[str, dict[str, Any]] = {}
        for subject_id, predicate, value, _observed_at, _claim_id in rows:
            values.setdefault(subject_id, {})[predicate] = value
        return values

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
                if (
                    current.subject_id != review.subject_id
                    or current.code != review.code
                ):
                    # A true id collision — different subject or reason.
                    raise RepositoryConflict(
                        f"Review exception id changed: {review.id}"
                    )
                # Same subject + code: the review already exists. Re-opening
                # is idempotent — first-opened wins (per-run fields like
                # opened_at and evidence ids legitimately differ between
                # encounters) and a human resolution is never reopened.
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

    def resolve_volatile_conflict_reviews(self, now: datetime) -> int:
        """Amnesty for conflict reviews opened under the pre-policy detector.

        Resolves open ``conflicting_authoritative_claims`` reviews whose
        disputed predicates are ALL volatile metrics — the detector no
        longer opens those, so the backlog would otherwise sit forever.
        Mixed reviews (any real predicate) are left for humans. Idempotent:
        the second run resolves nothing.
        """
        from radar.intelligence.contracts import VOLATILE_PREDICATES

        prefix = "Authoritative evidence conflicts for: "
        resolved = 0
        with self.database.session() as session:
            rows = session.scalars(
                select(ReviewExceptionRow).where(
                    ReviewExceptionRow.code
                    == "conflicting_authoritative_claims",
                    ReviewExceptionRow.resolved_at.is_(None),
                )
            ).all()
            for row in rows:
                if not row.message.startswith(prefix):
                    continue
                predicates = {
                    part.strip()
                    for part in row.message.removeprefix(prefix).split(",")
                    if part.strip()
                }
                if predicates and predicates <= VOLATILE_PREDICATES:
                    row.resolved_at = now
                    row.resolution = {
                        "resolution": "auto_amnesty_volatile_metrics",
                        "evidence_ids": [],
                        "note": (
                            "Volatile metric predicates are latest-wins "
                            "observations; the conflict detector no longer "
                            "flags them (policy 2026-08-05)"
                        ),
                    }
                    resolved += 1
        return resolved

    def resolve_same_origin_conflict_reviews(self, now: datetime) -> int:
        """Amnesty for conflicts whose evidence is one registry record.

        The detector now collapses registry-host evidence (REGISTRY_HOSTS)
        to its host: list-sweep vs detail-endpoint disagreement is refetch
        drift of ONE mutable record, resolved latest-wins. Reviews whose
        entire evidence set lives on a single registry host can no longer
        be produced — drain them. Anything with a non-registry source
        stays for humans. Idempotent.
        """
        from urllib.parse import urlsplit

        from radar.intelligence.contracts import REGISTRY_HOSTS

        resolved = 0
        with self.database.session() as session:
            rows = session.scalars(
                select(ReviewExceptionRow).where(
                    ReviewExceptionRow.code
                    == "conflicting_authoritative_claims",
                    ReviewExceptionRow.resolved_at.is_(None),
                )
            ).all()
            for row in rows:
                hosts: set[str] = set()
                for evidence_id in row.evidence_ids or []:
                    evidence_row = session.get(EvidenceRow, evidence_id)
                    if evidence_row is not None:
                        hosts.add(
                            urlsplit(evidence_row.source_url)
                            .netloc.casefold()
                        )
                if len(hosts) == 1 and hosts <= REGISTRY_HOSTS:
                    row.resolved_at = now
                    row.resolution = {
                        "resolution": "auto_amnesty_same_origin_drift",
                        "evidence_ids": [],
                        "note": (
                            "All conflicting evidence is one registry "
                            f"record ({next(iter(hosts))}); refetch drift "
                            "is latest-wins, not a dispute "
                            "(policy 2026-08-06)"
                        ),
                    }
                    resolved += 1
        return resolved

    def purge_invalid_lineage_parent_refs(self, now: datetime) -> int:
        """Remove edges whose declared parent is a filesystem path.

        Model cards carry training-time paths in base_model
        ("./distil-large-v3", "/root/.cache/…", "tmp/"); build_edges now
        rejects them, and this drains the stored backlog: junk edges are
        deleted and their unresolved-parent reviews resolved. Idempotent.
        Returns edges deleted + reviews resolved.
        """
        from radar.intelligence.lineage import is_valid_parent_repo

        prefix = "Declared lineage parent is not resolvable: "
        touched = 0
        with self.database.session() as session:
            edge_rows = session.scalars(select(LineageEdgeRow)).all()
            for edge_row in edge_rows:
                ref = edge_row.parent_external_ref.removeprefix("hf:")
                if not is_valid_parent_repo(ref):
                    session.delete(edge_row)
                    touched += 1
            review_rows = session.scalars(
                select(ReviewExceptionRow).where(
                    ReviewExceptionRow.code == "lineage-unresolved-parent",
                    ReviewExceptionRow.resolved_at.is_(None),
                )
            ).all()
            for row in review_rows:
                if not row.message.startswith(prefix):
                    continue
                ref = row.message.removeprefix(prefix).strip()
                if not is_valid_parent_repo(ref.removeprefix("hf:")):
                    row.resolved_at = now
                    row.resolution = {
                        "resolution": "auto_amnesty_invalid_parent_ref",
                        "evidence_ids": [],
                        "note": (
                            "Filesystem paths in base_model are training "
                            "artifacts, not lineage statements; build_edges "
                            "rejects them (policy 2026-08-06)"
                        ),
                    }
                    touched += 1
        return touched

    def resolve_collection_lineage_reviews(self, now: datetime) -> int:
        """Amnesty for lineage-conflict reviews from collection cards.

        A card declaring >= LINEAGE_COLLECTION_PARENT_THRESHOLD distinct
        parents is an aggregation/evaluation listing, not lineage — the
        detector no longer opens these; drain the stored ones. Idempotent.
        """
        from radar.intelligence.lineage import (
            LINEAGE_COLLECTION_PARENT_THRESHOLD,
        )

        prefix = "Conflicting lineage parents declared: "
        resolved = 0
        with self.database.session() as session:
            rows = session.scalars(
                select(ReviewExceptionRow).where(
                    ReviewExceptionRow.code == "lineage-conflict",
                    ReviewExceptionRow.resolved_at.is_(None),
                )
            ).all()
            for row in rows:
                if not row.message.startswith(prefix):
                    continue
                parents = [
                    part.strip()
                    for part in row.message.removeprefix(prefix).split(",")
                    if part.strip()
                ]
                if len(parents) >= LINEAGE_COLLECTION_PARENT_THRESHOLD:
                    row.resolved_at = now
                    row.resolution = {
                        "resolution": "auto_amnesty_collection_card",
                        "evidence_ids": [],
                        "note": (
                            "Cards declaring "
                            f">={LINEAGE_COLLECTION_PARENT_THRESHOLD} "
                            "distinct parents are aggregation/collection "
                            "listings, not lineage (policy 2026-08-05)"
                        ),
                    }
                    resolved += 1
        return resolved

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

    def upsert_lineage_edge(self, edge: LineageEdge) -> bool:
        """Create or update a lineage edge; returns True when anything changed.

        Identity is the edge ID (deterministic per child/parent-ref/relation);
        re-observing the same declaration is a no-op, while resolution updates
        (parent/root/review) and refreshed evidence overwrite in place.
        """
        with self.database.session() as session:
            row = session.get(LineageEdgeRow, edge.id)
            if row is None:
                session.add(
                    LineageEdgeRow(
                        id=edge.id,
                        child_release_id=edge.child_release_id,
                        parent_external_ref=edge.parent_external_ref,
                        parent_release_id=edge.parent_release_id,
                        root_release_id=edge.root_release_id,
                        relation=edge.relation.value,
                        declared=edge.declared,
                        confidence=edge.confidence,
                        evidence_ids=edge.evidence_ids,
                        extractor_version=edge.extractor_version,
                        review_status=edge.review_status.value,
                        observed_at=edge.observed_at,
                    )
                )
                return True
            if _lineage_from_row(row) == edge:
                return False
            if (
                row.child_release_id != edge.child_release_id
                or row.parent_external_ref != edge.parent_external_ref
                or row.relation != edge.relation.value
            ):
                raise RepositoryConflict(
                    f"Lineage edge id reused for different edge: {edge.id}"
                )
            row.parent_release_id = edge.parent_release_id
            row.root_release_id = edge.root_release_id
            row.declared = edge.declared
            row.confidence = edge.confidence
            row.evidence_ids = edge.evidence_ids
            row.extractor_version = edge.extractor_version
            row.review_status = edge.review_status.value
            row.observed_at = edge.observed_at
            return True

    def get_lineage_edge(self, edge_id: str) -> LineageEdge | None:
        with self.database.session() as session:
            row = session.get(LineageEdgeRow, edge_id)
            return _lineage_from_row(row) if row is not None else None

    def delete_lineage_edge(self, edge_id: str) -> bool:
        """Remove one edge — only meaningful for rejected suggestions."""
        with self.database.session() as session:
            row = session.get(LineageEdgeRow, edge_id)
            if row is None:
                return False
            session.delete(row)
            return True

    def list_lineage_for_child(
        self,
        child_release_id: str,
    ) -> list[LineageEdge]:
        with self.database.session() as session:
            rows = session.scalars(
                select(LineageEdgeRow)
                .where(LineageEdgeRow.child_release_id == child_release_id)
                .order_by(LineageEdgeRow.id)
            )
            return [_lineage_from_row(row) for row in rows]

    def list_lineage_children(
        self,
        parent_release_id: str,
    ) -> list[LineageEdge]:
        with self.database.session() as session:
            rows = session.scalars(
                select(LineageEdgeRow)
                .where(LineageEdgeRow.parent_release_id == parent_release_id)
                .order_by(LineageEdgeRow.id)
            )
            return [_lineage_from_row(row) for row in rows]

    def list_unresolved_lineage(
        self,
        limit: int | None = None,
    ) -> list[LineageEdge]:
        with self.database.session() as session:
            query = (
                select(LineageEdgeRow)
                .where(LineageEdgeRow.parent_release_id.is_(None))
                .order_by(LineageEdgeRow.id)
            )
            if limit is not None:
                query = query.limit(limit)
            return [_lineage_from_row(row) for row in session.scalars(query)]

    def list_all_lineage_edges(self) -> list[LineageEdge]:
        with self.database.session() as session:
            rows = session.scalars(
                select(LineageEdgeRow).order_by(LineageEdgeRow.id)
            )
            return [_lineage_from_row(row) for row in rows]

    def count_lineage_edges(self) -> int:
        with self.database.session() as session:
            return session.scalar(
                select(func.count()).select_from(LineageEdgeRow)
            ) or 0

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

    def update_workspace(self, workspace: Workspace) -> Workspace:
        now = datetime.now(UTC)
        payload = workspace.model_dump(mode="json")
        workspace_id = str(payload.pop("id"))
        schema_version = int(payload.pop("schema_version"))
        with self.database.session() as session:
            row = session.get(WorkspaceRow, workspace_id)
            if row is None:
                raise KeyError(f"Unknown workspace: {workspace_id}")
            row.schema_version = schema_version
            row.payload = payload
            row.updated_at = now
        return workspace

    def delete_workspace(self, workspace_id: str) -> bool:
        with self.database.session() as session:
            row = session.get(WorkspaceRow, workspace_id)
            if row is None:
                return False
            session.delete(row)
            return True

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

    def reconcile_legacy_platform_metadata(
        self,
        *,
        platform_id: str,
        name: str,
        repo_url: str,
        verified_at: str,
        payload: dict[str, object],
    ) -> tuple[bool, bool]:
        """Import a platform or refresh non-claim seed metadata safely.

        Hardware and feature values are represented by append-only claims and
        must use their own versioned migration. Source links and notes are
        materialized platform metadata, so correcting them keeps the stable
        platform identity and refreshes the projection in place.
        """
        with self.database.session() as session:
            existing = session.get(PlatformRow, platform_id)
            if existing is None:
                session.add(
                    PlatformRow(
                        id=platform_id,
                        name=name,
                        repo_url=repo_url,
                        verified_at=verified_at,
                        payload=payload,
                    )
                )
                return True, False

            existing_claim_fields = {
                "hardware": existing.payload.get("hardware"),
                "features": existing.payload.get("features"),
            }
            incoming_claim_fields = {
                "hardware": payload.get("hardware"),
                "features": payload.get("features"),
            }
            if (
                existing.name != name
                or existing.repo_url != repo_url
                or existing.verified_at != verified_at
                or existing_claim_fields != incoming_claim_fields
            ):
                raise RepositoryConflict(f"Platform id changed: {platform_id}")
            if existing.payload == payload:
                return False, False
            existing.payload = payload
            return False, True

    def count_platforms(self) -> int:
        with self.database.session() as session:
            return session.scalar(select(func.count()).select_from(PlatformRow)) or 0

    def record_platform_verification(
        self,
        platform_id: str,
        observed_at: datetime,
        *,
        evidence_id: str | None,
        success: bool,
    ) -> None:
        """Refresh current platform claims in place without growing stale history."""

        with self.database.session() as session:
            if session.get(PlatformRow, platform_id) is None:
                raise KeyError(f"Unknown platform: {platform_id}")
            rows = list(
                session.scalars(
                    select(ClaimRow).where(ClaimRow.subject_id == platform_id)
                )
            )
            for row in rows:
                row.state = (
                    ClaimState.VERIFIED.value
                    if success
                    else ClaimState.STALE.value
                )
                if success:
                    row.observed_at = observed_at
                    if evidence_id is not None and session.get(
                        ClaimEvidenceRow,
                        {"claim_id": row.id, "evidence_id": evidence_id},
                    ) is None:
                        session.add(
                            ClaimEvidenceRow(
                                claim_id=row.id,
                                evidence_id=evidence_id,
                            )
                        )

    def list_platforms(self) -> list[dict[str, Any]]:
        with self.database.session() as session:
            rows = list(
                session.scalars(select(PlatformRow).order_by(PlatformRow.id))
            )
            return [
                {
                    "id": row.id,
                    "name": row.name,
                    "repo_url": row.repo_url,
                    "verified_at": row.verified_at,
                    **row.payload,
                }
                for row in rows
            ]

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

    def latest_processed_attempts(self, kind: str) -> dict[str, datetime]:
        """Return the last completed attempt for each batched release."""
        with self.database.session() as session:
            rows = session.execute(
                select(JobRow.completed_at, JobRow.result)
                .where(
                    JobRow.kind == kind,
                    JobRow.status == JobStatus.COMPLETED.value,
                    JobRow.completed_at.is_not(None),
                )
                .order_by(JobRow.completed_at)
            )
            attempts: dict[str, datetime] = {}
            for completed_at, result in rows:
                normalized = _as_utc(completed_at)
                if normalized is None or not isinstance(result, dict):
                    continue
                for release_id in result.get("processed_ids") or []:
                    if isinstance(release_id, str):
                        attempts[release_id] = normalized
            return attempts
