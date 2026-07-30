from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_initial_migration_creates_intelligence_ledger(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    database_url = f"sqlite:///{tmp_path / 'migrated.db'}"
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")

    tables = set(inspect(create_engine(database_url)).get_table_names())
    assert {
        "alembic_version",
        "intelligence_evidence",
        "intelligence_claims",
        "intelligence_claim_evidence",
        "intelligence_publishers",
        "intelligence_families",
        "intelligence_releases",
        "intelligence_platforms",
        "intelligence_legacy_events",
        "intelligence_jobs",
        "intelligence_lifecycle_transitions",
        "intelligence_review_exceptions",
        "intelligence_source_health",
        "intelligence_compatibility",
        "intelligence_qualifications",
        "intelligence_workspaces",
        "intelligence_events",
        "intelligence_webhook_attempts",
    } <= tables
