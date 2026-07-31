from pathlib import Path

from radar.intelligence.database import Database
from radar.intelligence.migration import import_legacy_state
from radar.intelligence.repositories import SqlAlchemyIntelligenceRepository
from radar.intelligence.shadow import compare_legacy_projection

from .test_migration import seed_legacy_root


def test_imported_projection_matches_legacy_counts(tmp_path: Path) -> None:
    seed_legacy_root(tmp_path)
    database = Database(f"sqlite:///{tmp_path / 'data' / 'intelligence.db'}")
    database.create_schema()
    repository = SqlAlchemyIntelligenceRepository(database)
    import_legacy_state(tmp_path, repository)

    report = compare_legacy_projection(tmp_path, repository)

    assert report.is_equivalent is True
    assert report.legacy_models == report.canonical_models == 1
    assert report.legacy_platforms == report.canonical_platforms == 1
    assert report.differences == ()
