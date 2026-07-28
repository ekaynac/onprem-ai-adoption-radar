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

    def get_card(self, project: str) -> DecisionCard | None:
        """Return a single card by exact project name, or None if absent."""
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT payload FROM decision_cards WHERE project = ?", (project,)
            ).fetchone()
        return DecisionCard.model_validate_json(row[0]) if row else None

    def card_staleness_note(self) -> str | None:
        """Human-readable note when persisted cards span multiple scan days.

        The cards table upserts per-project, so after a partial/degraded scan
        the 'latest' view silently mixes ages. None = homogeneous (or empty).
        """
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute("SELECT updated_at FROM decision_cards").fetchall()
        if not rows:
            return None
        dates = sorted({row[0][:10] for row in rows})
        if len(dates) == 1:
            return None
        newest = dates[-1]
        stale = sum(1 for (stamp,) in rows if stamp[:10] != newest)
        return (
            f"{stale} of {len(rows)} cards predate the latest scan "
            f"(oldest {dates[0]}, newest {newest})"
        )
