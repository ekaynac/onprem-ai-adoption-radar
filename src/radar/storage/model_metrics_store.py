"""SQLite store of per-scan model metrics (mirror of metrics_store.py)."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel


class ModelMetrics(BaseModel):
    model_id: str
    run_id: str
    observed_at: datetime
    downloads: int | None = None
    likes: int | None = None
    min_memory_gb: float | None = None
    ring: str | None = None
    hardware_tier: str | None = None


_COLUMNS = (
    "model_id, run_id, observed_at, downloads, likes, "
    "min_memory_gb, ring, hardware_tier"
)


class ModelMetricsStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS model_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    downloads INTEGER,
                    likes INTEGER,
                    min_memory_gb REAL,
                    ring TEXT,
                    hardware_tier TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_model_metrics_model "
                "ON model_metrics(model_id, observed_at)"
            )

    def record(self, metrics: list[ModelMetrics]) -> None:
        if not metrics:
            return
        with sqlite3.connect(self.path) as conn:
            conn.executemany(
                f"INSERT INTO model_metrics({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [self._row(m) for m in metrics],
            )

    def latest(self, model_id: str, exclude_run: str | None = None) -> ModelMetrics | None:
        query = f"SELECT {_COLUMNS} FROM model_metrics WHERE model_id = ?"
        params: list[str] = [model_id]
        if exclude_run is not None:
            query += " AND run_id != ?"
            params.append(exclude_run)
        query += " ORDER BY observed_at DESC, id DESC LIMIT 1"
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(query, params).fetchone()
        return self._to_metrics(row) if row else None

    def history_for(self, model_id: str, limit: int = 50) -> list[ModelMetrics]:
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM model_metrics WHERE model_id = ? "
                "ORDER BY observed_at DESC, id DESC LIMIT ?",
                (model_id, limit),
            ).fetchall()
        return [self._to_metrics(r) for r in reversed(rows)]

    @staticmethod
    def _row(m: ModelMetrics) -> tuple:
        return (m.model_id, m.run_id, m.observed_at.isoformat(), m.downloads,
                m.likes, m.min_memory_gb, m.ring, m.hardware_tier)

    @staticmethod
    def _to_metrics(row: tuple) -> ModelMetrics:
        return ModelMetrics(
            model_id=row[0], run_id=row[1], observed_at=datetime.fromisoformat(row[2]),
            downloads=row[3], likes=row[4], min_memory_gb=row[5],
            ring=row[6], hardware_tier=row[7],
        )
