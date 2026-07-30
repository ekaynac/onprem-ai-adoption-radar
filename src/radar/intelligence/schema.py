"""SQLAlchemy schema for the canonical intelligence ledger."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PublisherRow(Base):
    __tablename__ = "intelligence_publishers"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    official_domains: Mapped[list[str]] = mapped_column(JSON)
    official_accounts: Mapped[list[str]] = mapped_column(JSON)
    aliases: Mapped[list[str]] = mapped_column(JSON)


class FamilyRow(Base):
    __tablename__ = "intelligence_families"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    publisher_id: Mapped[str] = mapped_column(
        ForeignKey("intelligence_publishers.id")
    )
    name: Mapped[str] = mapped_column(String(255))
    aliases: Mapped[list[str]] = mapped_column(JSON)


class ReleaseRow(Base):
    __tablename__ = "intelligence_releases"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    family_id: Mapped[str] = mapped_column(ForeignKey("intelligence_families.id"))
    publisher_id: Mapped[str] = mapped_column(
        ForeignKey("intelligence_publishers.id")
    )
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(40), index=True)
    lane: Mapped[str] = mapped_column(String(40), index=True)
    lifecycle: Mapped[str] = mapped_column(String(24), index=True)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    discovery_evidence_strength: Mapped[str] = mapped_column(String(40))


class PlatformRow(Base):
    __tablename__ = "intelligence_platforms"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    repo_url: Mapped[str] = mapped_column(Text)
    verified_at: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class LegacyEventRow(Base):
    __tablename__ = "intelligence_legacy_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    subject_id: Mapped[str] = mapped_column(String(255), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class JobRow(Base):
    __tablename__ = "intelligence_jobs"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    attempt: Mapped[int]
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)


class LifecycleTransitionRow(Base):
    __tablename__ = "intelligence_lifecycle_transitions"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    release_id: Mapped[str] = mapped_column(
        ForeignKey("intelligence_releases.id"), index=True
    )
    from_state: Mapped[str | None] = mapped_column(String(24))
    to_state: Mapped[str] = mapped_column(String(24))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON)


class ReviewExceptionRow(Base):
    __tablename__ = "intelligence_review_exceptions"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(255), index=True)
    code: Mapped[str] = mapped_column(String(80), index=True)
    message: Mapped[str] = mapped_column(Text)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class SourceHealthRow(Base):
    __tablename__ = "intelligence_source_health"

    source_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    latency_ms: Mapped[float | None] = mapped_column(Float)
    items_count: Mapped[int | None] = mapped_column(Integer)
    circuit_open_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class CompatibilityRow(Base):
    __tablename__ = "intelligence_compatibility"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    release_id: Mapped[str] = mapped_column(
        ForeignKey("intelligence_releases.id"), index=True
    )
    platform_id: Mapped[str] = mapped_column(String(255), index=True)
    platform_version: Mapped[str] = mapped_column(String(100))
    feature: Mapped[str] = mapped_column(String(100), index=True)
    support: Mapped[str] = mapped_column(String(24))
    evidence_level: Mapped[str] = mapped_column(String(24))
    evidence_ids: Mapped[list[str]] = mapped_column(JSON)
    hardware_scope: Mapped[list[str]] = mapped_column(JSON)


class QualificationRow(Base):
    __tablename__ = "intelligence_qualifications"

    release_id: Mapped[str] = mapped_column(
        ForeignKey("intelligence_releases.id"), primary_key=True
    )
    qualified: Mapped[bool]
    category: Mapped[str] = mapped_column(String(40), index=True)
    reasons: Mapped[list[str]] = mapped_column(JSON)
    assumptions: Mapped[list[str]] = mapped_column(JSON)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkspaceRow(Base):
    __tablename__ = "intelligence_workspaces"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    schema_version: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IntelligenceEventRow(Base):
    __tablename__ = "intelligence_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(16))
    type: Mapped[str] = mapped_column(String(100), index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    subject_id: Mapped[str] = mapped_column(String(255), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(255), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON)


class WebhookAttemptRow(Base):
    __tablename__ = "intelligence_webhook_attempts"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("intelligence_events.id"), index=True
    )
    destination: Mapped[str] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(Integer)
    signature: Mapped[str] = mapped_column(String(80))
    http_status: Mapped[int | None] = mapped_column(Integer)
    response_excerpt: Mapped[str] = mapped_column(Text)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    terminal: Mapped[bool]
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )

    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "destination",
            "attempt",
            name="uq_webhook_event_destination_attempt",
        ),
    )


class EvidenceRow(Base):
    __tablename__ = "intelligence_evidence"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    source_url: Mapped[str] = mapped_column(Text)
    strength: Mapped[str] = mapped_column(String(40), index=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    checksum: Mapped[str] = mapped_column(String(80))
    extractor_version: Mapped[str] = mapped_column(String(80))
    raw_snapshot_path: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("source_url", "checksum", name="uq_evidence_source_hash"),
    )


class ClaimRow(Base):
    __tablename__ = "intelligence_claims"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(255), index=True)
    predicate: Mapped[str] = mapped_column(String(100), index=True)
    value: Mapped[Any] = mapped_column(JSON)
    unit: Mapped[str | None] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(24), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supersedes_claim_id: Mapped[str | None] = mapped_column(
        ForeignKey("intelligence_claims.id")
    )

    __table_args__ = (
        Index("ix_claim_current", "subject_id", "predicate", "state", "observed_at"),
    )


class ClaimEvidenceRow(Base):
    __tablename__ = "intelligence_claim_evidence"

    claim_id: Mapped[str] = mapped_column(
        ForeignKey("intelligence_claims.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("intelligence_evidence.id"), primary_key=True
    )
