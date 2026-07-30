from __future__ import annotations

from pathlib import Path

from radar.intelligence.database import Database
from radar.intelligence.migration import import_legacy_state
from radar.intelligence.repositories import SqlAlchemyIntelligenceRepository


MODEL_SEED = """\
version: "1.0"
models:
  - id: sample-8b
    name: Sample 8B
    family: Sample
    hf_repo: acme/Sample-8B
    backer: {name: "Acme", type: startup}
    params_total: 8000000000
    context_length: 32768
    license: apache-2.0
    openness: open-permissive
    spec_verified: true
"""

PLATFORM_SEED = """\
version: "1.0"
platforms:
  - id: sample-engine
    name: Sample Engine
    repo_url: https://github.com/acme/sample-engine
    hardware: {nvidia: "yes"}
    features: {tensor_parallel: "yes"}
    sources: [https://github.com/acme/sample-engine]
    verified: "2026-07-30"
"""

MODEL_HISTORY = """\
{"model_id":"sample-8b","family":"Sample","change_type":"new","ring":"adopt","previous_ring":null,"run_id":"run-1","observed_at":"2026-07-30T08:00:00Z","reasons":["new to adopt"]}
"""

PUBLISHER_ALIAS_MODEL_SEED = """\
version: "1.0"
models:
  - id: sample-openai-upper
    name: Sample OpenAI Upper
    family: Sample
    hf_repo: openai/sample-upper
    backer: {name: "OpenAI", type: startup}
    openness: open-permissive
  - id: sample-openai-lower
    name: Sample OpenAI Lower
    family: Sample
    hf_repo: openai/sample-lower
    backer: {name: "openai", type: startup}
    openness: open-permissive
"""


def seed_legacy_root(root: Path) -> None:
    (root / "config").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    (root / "config" / "model-seed.yaml").write_text(MODEL_SEED, encoding="utf-8")
    (root / "config" / "platform-matrix.yaml").write_text(
        PLATFORM_SEED, encoding="utf-8"
    )
    (root / "data" / "model-history.jsonl").write_text(
        MODEL_HISTORY, encoding="utf-8"
    )


def test_import_is_idempotent_and_preserves_model_count(tmp_path: Path) -> None:
    seed_legacy_root(tmp_path)
    database = Database(f"sqlite:///{tmp_path / 'data' / 'intelligence.db'}")
    database.create_schema()
    repository = SqlAlchemyIntelligenceRepository(database)

    first = import_legacy_state(tmp_path, repository)
    second = import_legacy_state(tmp_path, repository)

    assert first.models_imported == 1
    assert first.platforms_imported == 1
    assert first.history_events_imported == 1
    assert second.models_imported == 0
    assert second.platforms_imported == 0
    assert second.history_events_imported == 0
    assert second.already_present == 3
    assert repository.count_releases() == 1
    assert repository.count_platforms() == 1


def test_verified_seed_value_becomes_cited_verified_claim(tmp_path: Path) -> None:
    seed_legacy_root(tmp_path)
    database = Database(f"sqlite:///{tmp_path / 'data' / 'intelligence.db'}")
    database.create_schema()
    repository = SqlAlchemyIntelligenceRepository(database)

    import_legacy_state(tmp_path, repository)

    claims = repository.list_claims_for_subject("release:legacy:sample-8b")
    params = next(claim for claim in claims if claim.predicate == "params_total")
    assert params.state.value == "verified"
    assert params.value == 8_000_000_000
    assert params.evidence_ids


def test_import_canonicalizes_publisher_aliases_before_upsert(
    tmp_path: Path,
) -> None:
    seed_legacy_root(tmp_path)
    (tmp_path / "config" / "model-seed.yaml").write_text(
        PUBLISHER_ALIAS_MODEL_SEED,
        encoding="utf-8",
    )
    database = Database(f"sqlite:///{tmp_path / 'data' / 'intelligence.db'}")
    database.create_schema()
    repository = SqlAlchemyIntelligenceRepository(database)

    report = import_legacy_state(tmp_path, repository)

    assert report.models_imported == 2
    assert repository.count_releases() == 2
