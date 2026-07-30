"""Create canonical catalog projections for legacy import.

Revision ID: 20260730_0002
Revises: 20260730_0001
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260730_0002"
down_revision: str | None = "20260730_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "intelligence_publishers",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("official_domains", sa.JSON(), nullable=False),
        sa.Column("official_accounts", sa.JSON(), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "intelligence_families",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("publisher_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["publisher_id"],
            ["intelligence_publishers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "intelligence_releases",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("family_id", sa.String(length=255), nullable=False),
        sa.Column("publisher_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("lane", sa.String(length=40), nullable=False),
        sa.Column("lifecycle", sa.String(length=24), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "discovery_evidence_strength", sa.String(length=40), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["intelligence_families.id"],
        ),
        sa.ForeignKeyConstraint(
            ["publisher_id"],
            ["intelligence_publishers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_intelligence_releases_category"),
        "intelligence_releases",
        ["category"],
        unique=False,
    )
    op.create_index(
        op.f("ix_intelligence_releases_lane"),
        "intelligence_releases",
        ["lane"],
        unique=False,
    )
    op.create_index(
        op.f("ix_intelligence_releases_lifecycle"),
        "intelligence_releases",
        ["lifecycle"],
        unique=False,
    )
    op.create_table(
        "intelligence_platforms",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("repo_url", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "intelligence_legacy_events",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("subject_id", sa.String(length=255), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_intelligence_legacy_events_kind"),
        "intelligence_legacy_events",
        ["kind"],
        unique=False,
    )
    op.create_index(
        op.f("ix_intelligence_legacy_events_subject_id"),
        "intelligence_legacy_events",
        ["subject_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_intelligence_legacy_events_subject_id"),
        table_name="intelligence_legacy_events",
    )
    op.drop_index(
        op.f("ix_intelligence_legacy_events_kind"),
        table_name="intelligence_legacy_events",
    )
    op.drop_table("intelligence_legacy_events")
    op.drop_table("intelligence_platforms")
    op.drop_index(
        op.f("ix_intelligence_releases_lifecycle"),
        table_name="intelligence_releases",
    )
    op.drop_index(
        op.f("ix_intelligence_releases_lane"),
        table_name="intelligence_releases",
    )
    op.drop_index(
        op.f("ix_intelligence_releases_category"),
        table_name="intelligence_releases",
    )
    op.drop_table("intelligence_releases")
    op.drop_table("intelligence_families")
    op.drop_table("intelligence_publishers")
