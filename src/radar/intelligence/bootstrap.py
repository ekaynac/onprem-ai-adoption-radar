"""Construction helpers for canonical intelligence persistence."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.engine import make_url

from radar.intelligence.database import Database
from radar.intelligence.repositories import SqlAlchemyIntelligenceRepository


def build_intelligence_repository(
    root: Path,
) -> tuple[Database, SqlAlchemyIntelligenceRepository]:
    default_url = f"sqlite:///{root.resolve() / 'data' / 'intelligence.db'}"
    database_url = os.environ.get("RADAR_DATABASE_URL", default_url)
    parsed_url = make_url(database_url)
    if (
        parsed_url.get_backend_name() == "sqlite"
        and parsed_url.database
        and parsed_url.database != ":memory:"
    ):
        Path(parsed_url.database).parent.mkdir(parents=True, exist_ok=True)
    database = Database(database_url)
    database.create_schema()
    return database, SqlAlchemyIntelligenceRepository(database)
