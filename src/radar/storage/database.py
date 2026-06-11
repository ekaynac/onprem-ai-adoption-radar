"""SQLite persistence for decision cards."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from radar.models import DecisionCard


class RadarDatabase:
    """Small SQLite wrapper for local persistence."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        """Create tables."""
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS decision_cards (
                    project TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    ring TEXT NOT NULL,
                    category TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def upsert_cards(self, cards: list[DecisionCard]) -> None:
        """Insert or update cards by project."""
        with sqlite3.connect(self.path) as conn:
            for card in cards:
                conn.execute(
                    """
                    INSERT INTO decision_cards(project, payload, ring, category, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(project) DO UPDATE SET
                        payload=excluded.payload,
                        ring=excluded.ring,
                        category=excluded.category,
                        updated_at=excluded.updated_at
                    """,
                    (
                        card.project,
                        card.model_dump_json(),
                        card.ring.value,
                        card.category.value,
                        card.last_reviewed_at.isoformat(),
                    ),
                )

    def list_cards(self) -> list[DecisionCard]:
        """Return all cards ordered by category and project."""
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                "SELECT payload FROM decision_cards ORDER BY category, project"
            ).fetchall()
        return [DecisionCard.model_validate_json(row[0]) for row in rows]
