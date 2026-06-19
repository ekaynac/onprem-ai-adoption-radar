"""Per-scan project metrics — the observed-data backbone for evidence scoring.

One row per project per scan. Growth-style evidence ("stars +1,240 since last
scan") compares the current scan's row against the latest row from a *previous*
run, so the store must be read before the current scan's rows are recorded
(or queried with ``exclude_run``).

Shares the SQLite file with the other stores; metrics are a rebuildable cache
of observations, not part of the durable history log.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel


class ProjectMetrics(BaseModel):
    """Observed metrics for one project at one scan."""

    project: str
    run_id: str
    observed_at: datetime
    stars: int | None = None
    forks: int | None = None
    open_issues: int | None = None
    license: str | None = None
    pushed_at: str | None = None
    releases_in_window: int = 0
    downloads_weekly: int | None = None
    hn_mentions: int | None = None
    advisories_open: int | None = None
    advisories_max_severity: str | None = None
    paper_mentions: int | None = None


_COLUMNS = (
    "project, run_id, observed_at, stars, forks, open_issues, license, "
    "pushed_at, releases_in_window, downloads_weekly, hn_mentions, "
    "advisories_open, advisories_max_severity, paper_mentions"
)


class MetricsStore:
    """SQLite-backed store of per-scan project metrics."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        """Create the metrics table if it does not exist."""
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS project_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    stars INTEGER,
                    forks INTEGER,
                    open_issues INTEGER,
                    license TEXT,
                    pushed_at TEXT,
                    releases_in_window INTEGER NOT NULL DEFAULT 0,
                    downloads_weekly INTEGER,
                    hn_mentions INTEGER,
                    advisories_open INTEGER,
                    advisories_max_severity TEXT,
                    paper_mentions INTEGER
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_metrics_project "
                "ON project_metrics(project, observed_at)"
            )
            cols = {row[1] for row in conn.execute("PRAGMA table_info(project_metrics)")}
            if "paper_mentions" not in cols:
                conn.execute("ALTER TABLE project_metrics ADD COLUMN paper_mentions INTEGER")

    def record(self, metrics: list[ProjectMetrics]) -> None:
        """Append one row per project for this scan. No-op for an empty list."""
        if not metrics:
            return
        with sqlite3.connect(self.path) as conn:
            conn.executemany(
                f"INSERT INTO project_metrics({_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [self._row(m) for m in metrics],
            )

    def latest(self, project: str, exclude_run: str | None = None) -> ProjectMetrics | None:
        """Most recent row for a project by observed_at.

        ``exclude_run`` skips the current scan's freshly written rows so
        growth comparisons see the previous scan.
        """
        query = f"SELECT {_COLUMNS} FROM project_metrics WHERE project = ?"
        params: list[str] = [project]
        if exclude_run is not None:
            query += " AND run_id != ?"
            params.append(exclude_run)
        query += " ORDER BY observed_at DESC, id DESC LIMIT 1"
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(query, params).fetchone()
        return self._to_metrics(row) if row else None

    def history_for(self, project: str, limit: int = 50) -> list[ProjectMetrics]:
        """A project's metric rows, oldest-first (at most ``limit`` most recent)."""
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM project_metrics WHERE project = ? "
                "ORDER BY observed_at DESC, id DESC LIMIT ?",
                (project, limit),
            ).fetchall()
        return [self._to_metrics(row) for row in reversed(rows)]

    @staticmethod
    def _row(m: ProjectMetrics) -> tuple:
        return (
            m.project,
            m.run_id,
            m.observed_at.isoformat(),
            m.stars,
            m.forks,
            m.open_issues,
            m.license,
            m.pushed_at,
            m.releases_in_window,
            m.downloads_weekly,
            m.hn_mentions,
            m.advisories_open,
            m.advisories_max_severity,
            m.paper_mentions,
        )

    @staticmethod
    def _to_metrics(row: tuple) -> ProjectMetrics:
        return ProjectMetrics(
            project=row[0],
            run_id=row[1],
            observed_at=datetime.fromisoformat(row[2]),
            stars=row[3],
            forks=row[4],
            open_issues=row[5],
            license=row[6],
            pushed_at=row[7],
            releases_in_window=row[8],
            downloads_weekly=row[9],
            hn_mentions=row[10],
            advisories_open=row[11],
            advisories_max_severity=row[12],
            paper_mentions=row[13],
        )
