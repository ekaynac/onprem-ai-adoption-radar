"""SQLite store of per-scan technique metrics (mirror of model_metrics_store.py)."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel


class TechniqueMetrics(BaseModel):
    technique_id: str
    run_id: str
    observed_at: datetime
    citation_count: int | None = None
    citation_source: str | None = None  # "s2" | "openalex" — velocity is same-source only
    resolved_impls: int | None = None
    ring: str | None = None


_COLUMNS = (
    "technique_id, run_id, observed_at, citation_count, citation_source, "
    "resolved_impls, ring"
)


class TechniqueMetricsStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS technique_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    technique_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    citation_count INTEGER,
                    citation_source TEXT,
                    resolved_impls INTEGER,
                    ring TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_technique_metrics_technique "
                "ON technique_metrics(technique_id, observed_at)"
            )

    def record(self, metrics: list[TechniqueMetrics]) -> None:
        if not metrics:
            return
        with sqlite3.connect(self.path) as conn:
            conn.executemany(
                f"INSERT INTO technique_metrics({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [self._row(m) for m in metrics],
            )

    def latest(
        self, technique_id: str, exclude_run: str | None = None,
    ) -> TechniqueMetrics | None:
        query = f"SELECT {_COLUMNS} FROM technique_metrics WHERE technique_id = ?"
        params: list[str] = [technique_id]
        if exclude_run is not None:
            query += " AND run_id != ?"
            params.append(exclude_run)
        query += " ORDER BY observed_at DESC, id DESC LIMIT 1"
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(query, params).fetchone()
        return self._to_metrics(row) if row else None

    def history_for(self, technique_id: str, limit: int = 50) -> list[TechniqueMetrics]:
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM technique_metrics WHERE technique_id = ? "
                "ORDER BY observed_at DESC, id DESC LIMIT ?",
                (technique_id, limit),
            ).fetchall()
        return [self._to_metrics(r) for r in reversed(rows)]

    @staticmethod
    def _row(m: TechniqueMetrics) -> tuple:
        return (m.technique_id, m.run_id, m.observed_at.isoformat(), m.citation_count,
                m.citation_source, m.resolved_impls, m.ring)

    @staticmethod
    def _to_metrics(row: tuple) -> TechniqueMetrics:
        return TechniqueMetrics(
            technique_id=row[0], run_id=row[1],
            observed_at=datetime.fromisoformat(row[2]),
            citation_count=row[3], citation_source=row[4],
            resolved_impls=row[5], ring=row[6],
        )
