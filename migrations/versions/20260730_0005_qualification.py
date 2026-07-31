"""Add compatibility and qualification projections.

Revision ID: 20260730_0005
Revises: 20260730_0004
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260730_0005"
down_revision: str | None = "20260730_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "intelligence_compatibility",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("release_id", sa.String(length=255), nullable=False),
        sa.Column("platform_id", sa.String(length=255), nullable=False),
        sa.Column("platform_version", sa.String(length=100), nullable=False),
        sa.Column("feature", sa.String(length=100), nullable=False),
        sa.Column("support", sa.String(length=24), nullable=False),
        sa.Column("evidence_level", sa.String(length=24), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("hardware_scope", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["intelligence_releases.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("release_id", "platform_id", "feature"):
        op.create_index(
            op.f(f"ix_intelligence_compatibility_{column}"),
            "intelligence_compatibility",
            [column],
            unique=False,
        )
    op.create_table(
        "intelligence_qualifications",
        sa.Column("release_id", sa.String(length=255), nullable=False),
        sa.Column("qualified", sa.Boolean(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("assumptions", sa.JSON(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["intelligence_releases.id"],
        ),
        sa.PrimaryKeyConstraint("release_id"),
    )
    op.create_index(
        op.f("ix_intelligence_qualifications_category"),
        "intelligence_qualifications",
        ["category"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_intelligence_qualifications_category"),
        table_name="intelligence_qualifications",
    )
    op.drop_table("intelligence_qualifications")
    for column in ("feature", "platform_id", "release_id"):
        op.drop_index(
            op.f(f"ix_intelligence_compatibility_{column}"),
            table_name="intelligence_compatibility",
        )
    op.drop_table("intelligence_compatibility")
