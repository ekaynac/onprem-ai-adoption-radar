"""Add lifecycle, review, and source-health projections.

Revision ID: 20260730_0004
Revises: 20260730_0003
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260730_0004"
down_revision: str | None = "20260730_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "intelligence_lifecycle_transitions",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("release_id", sa.String(length=255), nullable=False),
        sa.Column("from_state", sa.String(length=24), nullable=True),
        sa.Column("to_state", sa.String(length=24), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["intelligence_releases.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_intelligence_lifecycle_transitions_release_id"),
        "intelligence_lifecycle_transitions",
        ["release_id"],
        unique=False,
    )
    op.create_table(
        "intelligence_review_exceptions",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("subject_id", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_intelligence_review_exceptions_subject_id"),
        "intelligence_review_exceptions",
        ["subject_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_intelligence_review_exceptions_code"),
        "intelligence_review_exceptions",
        ["code"],
        unique=False,
    )
    op.create_table(
        "intelligence_source_health",
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("items_count", sa.Integer(), nullable=True),
        sa.Column("circuit_open_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("source_id"),
    )


def downgrade() -> None:
    op.drop_table("intelligence_source_health")
    op.drop_index(
        op.f("ix_intelligence_review_exceptions_code"),
        table_name="intelligence_review_exceptions",
    )
    op.drop_index(
        op.f("ix_intelligence_review_exceptions_subject_id"),
        table_name="intelligence_review_exceptions",
    )
    op.drop_table("intelligence_review_exceptions")
    op.drop_index(
        op.f("ix_intelligence_lifecycle_transitions_release_id"),
        table_name="intelligence_lifecycle_transitions",
    )
    op.drop_table("intelligence_lifecycle_transitions")
