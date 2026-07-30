"""Create the canonical evidence and claim ledger.

Revision ID: 20260730_0001
Revises:
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260730_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "intelligence_evidence",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("strength", sa.String(length=40), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checksum", sa.String(length=80), nullable=False),
        sa.Column("extractor_version", sa.String(length=80), nullable=False),
        sa.Column("raw_snapshot_path", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_url", "checksum", name="uq_evidence_source_hash"
        ),
    )
    op.create_index(
        op.f("ix_intelligence_evidence_retrieved_at"),
        "intelligence_evidence",
        ["retrieved_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_intelligence_evidence_strength"),
        "intelligence_evidence",
        ["strength"],
        unique=False,
    )
    op.create_table(
        "intelligence_claims",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("subject_id", sa.String(length=255), nullable=False),
        sa.Column("predicate", sa.String(length=100), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("unit", sa.String(length=40), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supersedes_claim_id", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(
            ["supersedes_claim_id"],
            ["intelligence_claims.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_claim_current",
        "intelligence_claims",
        ["subject_id", "predicate", "state", "observed_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_intelligence_claims_predicate"),
        "intelligence_claims",
        ["predicate"],
        unique=False,
    )
    op.create_index(
        op.f("ix_intelligence_claims_state"),
        "intelligence_claims",
        ["state"],
        unique=False,
    )
    op.create_index(
        op.f("ix_intelligence_claims_subject_id"),
        "intelligence_claims",
        ["subject_id"],
        unique=False,
    )
    op.create_table(
        "intelligence_claim_evidence",
        sa.Column("claim_id", sa.String(length=255), nullable=False),
        sa.Column("evidence_id", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["intelligence_claims.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["intelligence_evidence.id"],
        ),
        sa.PrimaryKeyConstraint("claim_id", "evidence_id"),
    )


def downgrade() -> None:
    op.drop_table("intelligence_claim_evidence")
    op.drop_index(
        op.f("ix_intelligence_claims_subject_id"),
        table_name="intelligence_claims",
    )
    op.drop_index(
        op.f("ix_intelligence_claims_state"),
        table_name="intelligence_claims",
    )
    op.drop_index(
        op.f("ix_intelligence_claims_predicate"),
        table_name="intelligence_claims",
    )
    op.drop_index("ix_claim_current", table_name="intelligence_claims")
    op.drop_table("intelligence_claims")
    op.drop_index(
        op.f("ix_intelligence_evidence_strength"),
        table_name="intelligence_evidence",
    )
    op.drop_index(
        op.f("ix_intelligence_evidence_retrieved_at"),
        table_name="intelligence_evidence",
    )
    op.drop_table("intelligence_evidence")
