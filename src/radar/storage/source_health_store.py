"""Per-scan, per-source signal counts — for dead-feed detection.

Each scan records how many raw signals every source produced. A source that
yields nothing for several consecutive scans is probably broken (a moved feed,
a renamed repo, a captive portal) rather than merely quiet, so it is flagged
as stale in `radar seed list` and the dashboard.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path


# Scans run daily, so a 7-scan window means "produced nothing for ~a week"
# before a source is called stale. A shorter window false-positives on healthy
# low-frequency feeds (e.g. a blog that posts ~weekly).
DEFAULT_STALE_WINDOW = 7


class SourceHealthStore:
    """SQLite-backed per-source signal-count history."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_health (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    signal_count INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_source_health_source "
                "ON source_health(source_id, observed_at)"
            )

    def record(
        self,
        run_id: str,
        observed_at: datetime,
        counts: dict[str, int],
    ) -> None:
        """Record one row per source for this scan. No-op for an empty dict."""
        if not counts:
            return
        with sqlite3.connect(self.path) as conn:
            conn.executemany(
                "INSERT INTO source_health(source_id, run_id, observed_at, signal_count) "
                "VALUES (?, ?, ?, ?)",
                [
                    (source_id, run_id, observed_at.isoformat(), count)
                    for source_id, count in counts.items()
                ],
            )

    def latest_counts(self) -> dict[str, int]:
        """Signal count per source from the most recent scan that recorded it."""
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                """
                SELECT source_id, signal_count
                FROM source_health
                WHERE (source_id, observed_at) IN (
                    SELECT source_id, MAX(observed_at)
                    FROM source_health GROUP BY source_id
                )
                """
            ).fetchall()
        return {row[0]: row[1] for row in rows}

    def stale_source_ids(self, window: int = DEFAULT_STALE_WINDOW) -> set[str]:
        """Sources whose last ``window`` recorded scans all produced zero signals.

        A source with fewer than ``window`` recorded scans is never stale —
        too little evidence to call it dead.
        """
        with sqlite3.connect(self.path) as conn:
            source_ids = [
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT source_id FROM source_health"
                )
            ]
            stale: set[str] = set()
            for source_id in source_ids:
                recent = conn.execute(
                    "SELECT signal_count FROM source_health WHERE source_id = ? "
                    "ORDER BY observed_at DESC, id DESC LIMIT ?",
                    (source_id, window),
                ).fetchall()
                if len(recent) >= window and all(count == 0 for (count,) in recent):
                    stale.add(source_id)
        return stale
