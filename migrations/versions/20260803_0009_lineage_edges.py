"""Model lineage edges: declared and inferred parent relationships.

Revision ID: 20260803_0009
Revises: 20260730_0008
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260803_0009"
down_revision: str | None = "20260730_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "intelligence_lineage_edges",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("child_release_id", sa.String(length=255), nullable=False),
        sa.Column("parent_external_ref", sa.String(length=512), nullable=False),
        sa.Column("parent_release_id", sa.String(length=255), nullable=True),
        sa.Column("root_release_id", sa.String(length=255), nullable=True),
        sa.Column("relation", sa.String(length=24), nullable=False),
        sa.Column("declared", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("extractor_version", sa.String(length=80), nullable=False),
        sa.Column("review_status", sa.String(length=16), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["child_release_id"], ["intelligence_releases.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "child_release_id",
            "parent_external_ref",
            "relation",
            name="uq_lineage_child_parent_relation",
        ),
    )
    op.create_index(
        "ix_intelligence_lineage_edges_child_release_id",
        "intelligence_lineage_edges",
        ["child_release_id"],
    )
    op.create_index(
        "ix_intelligence_lineage_edges_parent_external_ref",
        "intelligence_lineage_edges",
        ["parent_external_ref"],
    )
    op.create_index(
        "ix_intelligence_lineage_edges_parent_release_id",
        "intelligence_lineage_edges",
        ["parent_release_id"],
    )
    op.create_index(
        "ix_intelligence_lineage_edges_root_release_id",
        "intelligence_lineage_edges",
        ["root_release_id"],
    )
    op.create_index(
        "ix_intelligence_lineage_edges_relation",
        "intelligence_lineage_edges",
        ["relation"],
    )
    op.create_index(
        "ix_intelligence_lineage_edges_review_status",
        "intelligence_lineage_edges",
        ["review_status"],
    )


def downgrade() -> None:
    op.drop_table("intelligence_lineage_edges")
