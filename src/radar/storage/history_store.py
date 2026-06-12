"""Append-only per-project observation history (Phase C).

Each scan computes deltas (new/promoted/demoted/updated projects). Those change
events are appended here so every project accumulates a durable timeline: when
it was first seen, every ring move, and every meaningful update. This is what
lets reports grow day by day instead of only showing the latest snapshot.

The history shares the same SQLite file as the decision cards but owns its own
table. It is strictly append-only — events are never updated or deleted.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from radar.models import Category, Ring
from radar.pipeline.delta import CardDelta, ChangeType


class ProjectHistoryEvent(BaseModel):
    """A single recorded change for a project at a point in time."""

    project: str
    category: Category
    change_type: ChangeType
    ring: Ring
    previous_ring: Ring | None = None
    run_id: str
    observed_at: datetime
    reasons: list[str] = Field(default_factory=list)


class ProjectHistorySummary(BaseModel):
    """Aggregated timeline for a single project."""

    project: str
    category: Category
    current_ring: Ring
    first_seen: datetime
    last_change_at: datetime
    last_change_type: ChangeType
    change_count: int


class HistoryStore:
    """SQLite-backed append-only store for project change history."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        """Create the history table if it does not exist."""
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS project_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project TEXT NOT NULL,
                    category TEXT NOT NULL,
                    change_type TEXT NOT NULL,
                    ring TEXT NOT NULL,
                    previous_ring TEXT,
                    run_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    reasons TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_history_project "
                "ON project_history(project, id)"
            )

    def record_deltas(
        self,
        deltas: list[CardDelta],
        run_id: str,
        observed_at: datetime,
    ) -> None:
        """Append one history event per delta. No-op for an empty list."""
        if not deltas:
            return
        with sqlite3.connect(self.path) as conn:
            conn.executemany(
                """
                INSERT INTO project_history(
                    project, category, change_type, ring, previous_ring,
                    run_id, observed_at, reasons
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        delta.project,
                        delta.category.value,
                        delta.change_type.value,
                        delta.current_ring.value,
                        delta.previous_ring.value if delta.previous_ring else None,
                        run_id,
                        observed_at.isoformat(),
                        json.dumps(delta.reasons),
                    )
                    for delta in deltas
                ],
            )

    def history_for(self, project: str) -> list[ProjectHistoryEvent]:
        """Return a project's events oldest-first (insertion order)."""
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                """
                SELECT project, category, change_type, ring, previous_ring,
                       run_id, observed_at, reasons
                FROM project_history
                WHERE project = ?
                ORDER BY id
                """,
                (project,),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def summaries(self) -> list[ProjectHistorySummary]:
        """Return one aggregated summary per project, ordered by project name."""
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                """
                SELECT project, category, change_type, ring, previous_ring,
                       run_id, observed_at, reasons
                FROM project_history
                ORDER BY id
                """
            ).fetchall()

        events_by_project: dict[str, list[ProjectHistoryEvent]] = {}
        for row in rows:
            event = self._row_to_event(row)
            events_by_project.setdefault(event.project, []).append(event)

        summaries = [
            ProjectHistorySummary(
                project=project,
                category=events[-1].category,
                current_ring=events[-1].ring,
                first_seen=events[0].observed_at,
                last_change_at=events[-1].observed_at,
                last_change_type=events[-1].change_type,
                change_count=len(events),
            )
            for project, events in events_by_project.items()
        ]
        return sorted(summaries, key=lambda s: s.project.lower())

    @staticmethod
    def _row_to_event(row: tuple) -> ProjectHistoryEvent:
        return ProjectHistoryEvent(
            project=row[0],
            category=Category(row[1]),
            change_type=ChangeType(row[2]),
            ring=Ring(row[3]),
            previous_ring=Ring(row[4]) if row[4] else None,
            run_id=row[5],
            observed_at=datetime.fromisoformat(row[6]),
            reasons=json.loads(row[7]),
        )
