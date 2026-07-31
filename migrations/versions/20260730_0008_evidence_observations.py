"""Allow repeated observations of unchanged source content.

Revision ID: 20260730_0008
Revises: 20260730_0007
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "20260730_0008"
down_revision: str | None = "20260730_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("intelligence_evidence") as batch:
        batch.drop_constraint(
            "uq_evidence_source_hash",
            type_="unique",
        )


def downgrade() -> None:
    with op.batch_alter_table("intelligence_evidence") as batch:
        batch.create_unique_constraint(
            "uq_evidence_source_hash",
            ["source_url", "checksum"],
        )
