"""SQLAlchemy schema for the canonical intelligence ledger."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


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

