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


def deltas_to_events(
    deltas: list[CardDelta],
    run_id: str,
    observed_at: datetime,
) -> list[ProjectHistoryEvent]:
    """Convert a scan's deltas into durable history events."""
    return [
        ProjectHistoryEvent(
            project=delta.project,
            category=delta.category,
            change_type=delta.change_type,
            ring=delta.current_ring,
            previous_ring=delta.previous_ring,
            run_id=run_id,
            observed_at=observed_at,
            reasons=delta.reasons,
        )
        for delta in deltas
    ]


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
    corrects_run_id: str | None = None


class ProjectHistorySummary(BaseModel):
    """Aggregated timeline for a single project."""

    project: str
    category: Category
    current_ring: Ring
    first_seen: datetime
    last_change_at: datetime
    last_change_type: ChangeType
    change_count: int


def apply_corrections(events: list[ProjectHistoryEvent]) -> list[ProjectHistoryEvent]:
    """The effective timeline: corrected (project, run) pairs removed.

    A `corrected` event neutralizes every event its project recorded in
    `corrects_run_id`'s run (a proven collection-outage artifact). Marker
    events themselves are also excluded — they are display-only. Raw readers
    (feeds, the timeline page) still see everything via the unfiltered list.
    """
    corrected_pairs = {
        (e.project, e.corrects_run_id)
        for e in events
        if e.change_type == ChangeType.CORRECTED and e.corrects_run_id
    }
    return [
        e
        for e in events
        if e.change_type != ChangeType.CORRECTED
        and (e.project, e.run_id) not in corrected_pairs
    ]


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
            # Migration: pre-2026-07 tables lack the corrects_run_id column.
            # ALTER is idempotent-by-exception: "duplicate column name" means done.
            try:
                conn.execute(
                    "ALTER TABLE project_history ADD COLUMN corrects_run_id TEXT"
                )
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc):
                    raise

    def record_deltas(
        self,
        deltas: list[CardDelta],
        run_id: str,
        observed_at: datetime,
    ) -> None:
        """Append one history event per delta. No-op for an empty list."""
        self.add_events(deltas_to_events(deltas, run_id, observed_at))

    def add_events(self, events: list[ProjectHistoryEvent]) -> None:
        """Append events to the table. No-op for an empty list."""
        if not events:
            return
        with sqlite3.connect(self.path) as conn:
            conn.executemany(
                """
                INSERT INTO project_history(
                    project, category, change_type, ring, previous_ring,
                    run_id, observed_at, reasons, corrects_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [self._event_row(event) for event in events],
            )

    def import_events(self, events: list[ProjectHistoryEvent]) -> int:
        """Insert events not already present (idempotent rehydration).

        Used to rebuild the SQLite projection from the durable JSONL log. The
        natural key is (project, run_id, change_type) — within a run a project
        has at most one event of a given change type. Returns the count inserted.
        """
        existing = self._event_keys()
        fresh = [e for e in events if self._event_key(e) not in existing]
        self.add_events(fresh)
        return len(fresh)

    def has_events(self) -> bool:
        """Whether any history has been recorded."""
        with sqlite3.connect(self.path) as conn:
            return conn.execute("SELECT 1 FROM project_history LIMIT 1").fetchone() is not None

    def all_events(self) -> list[ProjectHistoryEvent]:
        """Return every recorded event, oldest-first."""
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                """
                SELECT project, category, change_type, ring, previous_ring,
                       run_id, observed_at, reasons, corrects_run_id
                FROM project_history
                ORDER BY id
                """
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def seen_projects(self) -> set[str]:
        """All projects that have ever appeared in the history."""
        with sqlite3.connect(self.path) as conn:
            return {row[0] for row in conn.execute("SELECT DISTINCT project FROM project_history")}

    def _event_keys(self) -> set[tuple[str, str, str]]:
        with sqlite3.connect(self.path) as conn:
            return {
                (row[0], row[1], row[2])
                for row in conn.execute(
                    "SELECT project, run_id, change_type FROM project_history"
                )
            }

    @staticmethod
    def _event_key(event: ProjectHistoryEvent) -> tuple[str, str, str]:
        return (event.project, event.run_id, event.change_type.value)

    @staticmethod
    def _event_row(event: ProjectHistoryEvent) -> tuple:
        return (
            event.project,
            event.category.value,
            event.change_type.value,
            event.ring.value,
            event.previous_ring.value if event.previous_ring else None,
            event.run_id,
            event.observed_at.isoformat(),
            json.dumps(event.reasons),
            event.corrects_run_id,
        )

    def history_for(self, project: str) -> list[ProjectHistoryEvent]:
        """Return a project's events oldest-first (insertion order)."""
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                """
                SELECT project, category, change_type, ring, previous_ring,
                       run_id, observed_at, reasons, corrects_run_id
                FROM project_history
                WHERE project = ?
                ORDER BY id
                """,
                (project,),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def summaries(self) -> list[ProjectHistorySummary]:
        """Return one aggregated summary per project, ordered by project name.

        Computed over the *effective* view: corrected (project, run) pairs are
        removed via `apply_corrections`. A project with no effective events
        after filtering (e.g. its only history was a collection-outage
        artifact) is omitted entirely.
        """
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                """
                SELECT project, category, change_type, ring, previous_ring,
                       run_id, observed_at, reasons, corrects_run_id
                FROM project_history
                ORDER BY id
                """
            ).fetchall()

        events_by_project: dict[str, list[ProjectHistoryEvent]] = {}
        for row in rows:
            event = self._row_to_event(row)
            events_by_project.setdefault(event.project, []).append(event)

        # Order by observed_at, not insertion order: logs merged from several
        # machines (or rehydrated from a concatenated JSONL file) may arrive
        # out of chronological order. Stable sort keeps within-run order.
        summaries = []
        for project, unordered in events_by_project.items():
            events = apply_corrections(sorted(unordered, key=lambda e: e.observed_at))
            if not events:
                continue
            summaries.append(
                ProjectHistorySummary(
                    project=project,
                    category=events[-1].category,
                    current_ring=events[-1].ring,
                    first_seen=events[0].observed_at,
                    last_change_at=events[-1].observed_at,
                    last_change_type=events[-1].change_type,
                    change_count=len(events),
                )
            )
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
            corrects_run_id=row[8],
        )
