"""Add the durable intelligence job ledger.

Revision ID: 20260730_0003
Revises: 20260730_0002
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260730_0003"
down_revision: str | None = "20260730_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "intelligence_jobs",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        op.f("ix_intelligence_jobs_kind"),
        "intelligence_jobs",
        ["kind"],
        unique=False,
    )
    op.create_index(
        op.f("ix_intelligence_jobs_status"),
        "intelligence_jobs",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_intelligence_jobs_status"),
        table_name="intelligence_jobs",
    )
    op.drop_index(
        op.f("ix_intelligence_jobs_kind"),
        table_name="intelligence_jobs",
    )
    op.drop_table("intelligence_jobs")
