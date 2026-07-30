"""Construction helpers for canonical intelligence persistence."""

from __future__ import annotations

import os
from pathlib import Path

from radar.intelligence.database import Database
from radar.intelligence.repositories import SqlAlchemyIntelligenceRepository


def build_intelligence_repository(
    root: Path,
) -> tuple[Database, SqlAlchemyIntelligenceRepository]:
    default_url = f"sqlite:///{root.resolve() / 'data' / 'intelligence.db'}"
    database = Database(os.environ.get("RADAR_DATABASE_URL", default_url))
    database.create_schema()
    return database, SqlAlchemyIntelligenceRepository(database)

