"""Add versioned intelligence events and webhook delivery attempts.

Revision ID: 20260730_0007
Revises: 20260730_0006
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260730_0007"
down_revision: str | None = "20260730_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "intelligence_events",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subject_id", sa.String(length=255), nullable=False),
        sa.Column("workspace_id", sa.String(length=255), nullable=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_intelligence_events_type",
        "intelligence_events",
        ["type"],
    )
    op.create_index(
        "ix_intelligence_events_occurred_at",
        "intelligence_events",
        ["occurred_at"],
    )
    op.create_index(
        "ix_intelligence_events_subject_id",
        "intelligence_events",
        ["subject_id"],
    )
    op.create_index(
        "ix_intelligence_events_workspace_id",
        "intelligence_events",
        ["workspace_id"],
    )
    op.create_table(
        "intelligence_webhook_attempts",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("destination", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("signature", sa.String(length=80), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("response_excerpt", sa.Text(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal", sa.Boolean(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["intelligence_events.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_id",
            "destination",
            "attempt",
            name="uq_webhook_event_destination_attempt",
        ),
    )
    op.create_index(
        "ix_intelligence_webhook_attempts_event_id",
        "intelligence_webhook_attempts",
        ["event_id"],
    )
    op.create_index(
        "ix_intelligence_webhook_attempts_next_retry_at",
        "intelligence_webhook_attempts",
        ["next_retry_at"],
    )
    op.create_index(
        "ix_intelligence_webhook_attempts_attempted_at",
        "intelligence_webhook_attempts",
        ["attempted_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_intelligence_webhook_attempts_attempted_at",
        table_name="intelligence_webhook_attempts",
    )
    op.drop_index(
        "ix_intelligence_webhook_attempts_next_retry_at",
        table_name="intelligence_webhook_attempts",
    )
    op.drop_index(
        "ix_intelligence_webhook_attempts_event_id",
        table_name="intelligence_webhook_attempts",
    )
    op.drop_table("intelligence_webhook_attempts")
    op.drop_index(
        "ix_intelligence_events_workspace_id",
        table_name="intelligence_events",
    )
    op.drop_index(
        "ix_intelligence_events_subject_id",
        table_name="intelligence_events",
    )
    op.drop_index(
        "ix_intelligence_events_occurred_at",
        table_name="intelligence_events",
    )
    op.drop_index(
        "ix_intelligence_events_type",
        table_name="intelligence_events",
    )
    op.drop_table("intelligence_events")
