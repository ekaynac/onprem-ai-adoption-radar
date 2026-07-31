from __future__ import annotations

from radar.intelligence.database import Database
from radar.intelligence.migration import import_legacy_state
from radar.intelligence.repositories import SqlAlchemyIntelligenceRepository
from radar.intelligence.shadow import compare_legacy_projection


def seed_legacy_root(root) -> None:
    (root / "config").mkdir()
    (root / "data").mkdir()
    (root / "config" / "model-seed.yaml").write_text(
        """\
version: "1.0"
models:
  - id: sample-8b
    name: Sample 8B
    family: Sample
    hf_repo: acme/Sample-8B
    backer: {name: Acme, type: startup}
    params_total: 8000000000
    context_length: 32768
    license: apache-2.0
    openness: open-permissive
    spec_verified: true
""",
        encoding="utf-8",
    )
    (root / "config" / "platform-matrix.yaml").write_text(
        """\
version: "1.0"
platforms:
  - id: sample-engine
    name: Sample Engine
    repo_url: https://github.com/acme/sample-engine
    hardware: {nvidia: "yes"}
    features: {tensor_parallel: "yes"}
    sources: [https://github.com/acme/sample-engine]
    verified: "2026-07-30"
""",
        encoding="utf-8",
    )
    (root / "data" / "model-history.jsonl").write_text(
        (
            '{"model_id":"sample-8b","family":"Sample","change_type":"new",'
            '"ring":"adopt","previous_ring":null,"run_id":"run-1",'
            '"observed_at":"2026-07-30T08:00:00Z","reasons":["new"]}\n'
        ),
        encoding="utf-8",
    )


def test_migration_rehearsal_is_idempotent_and_shadow_equivalent(tmp_path) -> None:
    seed_legacy_root(tmp_path)
    database = Database(f"sqlite:///{tmp_path / 'data' / 'intelligence.db'}")
    database.create_schema()
    repository = SqlAlchemyIntelligenceRepository(database)

    first = import_legacy_state(tmp_path, repository)
    second = import_legacy_state(tmp_path, repository)
    shadow = compare_legacy_projection(tmp_path, repository)

    assert first.models_imported == 1
    assert second.models_imported == 0
    assert second.platforms_imported == 0
    assert second.history_events_imported == 0
    assert shadow.is_equivalent
