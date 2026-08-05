from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete

from radar.intelligence.contracts import (
    ClaimState,
    EvidenceObservation,
    EvidenceStrength,
    LifecycleState,
)
from radar.intelligence.database import Database
from radar.intelligence.migration import import_legacy_state
from radar.intelligence.repositories import SqlAlchemyIntelligenceRepository
from radar.intelligence.schema import LifecycleTransitionRow


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
    publisher_ids = {item.id for item in repository.list_publishers()}
    assert "publisher:moonshot-ai" in publisher_ids
    assert "publisher:platform:vllm" in publisher_ids


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


def test_reimport_preserves_operational_claim_state_promotion(tmp_path: Path) -> None:
    seed_legacy_root(tmp_path)
    (tmp_path / "config" / "model-seed.yaml").write_text(
        MODEL_SEED.replace("spec_verified: true", "spec_verified: false"),
        encoding="utf-8",
    )
    database = Database(f"sqlite:///{tmp_path / 'data' / 'intelligence.db'}")
    database.create_schema()
    repository = SqlAlchemyIntelligenceRepository(database)
    import_legacy_state(tmp_path, repository)
    claim_id = "claim:legacy:sample-8b:context_length"
    repository.set_claim_state(claim_id, ClaimState.VERIFIED)

    import_legacy_state(tmp_path, repository)

    claim = repository.get_claim(claim_id)
    assert claim is not None
    assert claim.state is ClaimState.VERIFIED


def test_reimport_reconciles_corrected_legacy_platform_metadata(tmp_path: Path) -> None:
    seed_legacy_root(tmp_path)
    database = Database(f"sqlite:///{tmp_path / 'data' / 'intelligence.db'}")
    database.create_schema()
    repository = SqlAlchemyIntelligenceRepository(database)
    import_legacy_state(tmp_path, repository)
    corrected_source = "https://github.com/acme/sample-engine/blob/main/docs/install.md"
    (tmp_path / "config" / "platform-matrix.yaml").write_text(
        PLATFORM_SEED.replace(
            "https://github.com/acme/sample-engine]",
            f"{corrected_source}]",
        ),
        encoding="utf-8",
    )

    corrected = import_legacy_state(tmp_path, repository)
    repeated = import_legacy_state(tmp_path, repository)

    assert corrected.platforms_imported == 0
    assert repeated.platforms_imported == 0
    assert repository.count_platforms() == 1
    platform = next(
        row
        for row in repository.list_platforms()
        if row["name"] == "Sample Engine"
    )
    assert platform["sources"] == [corrected_source]
    evidence = repository.get_evidence(
        next(
            claim.evidence_ids[-1]
            for claim in repository.list_claims_for_subject(
                "platform:legacy:sample-engine"
            )
        )
    )
    assert evidence is not None
    assert evidence.source_url == corrected_source


def test_verified_seed_records_detected_to_verified_transition(tmp_path: Path) -> None:
    seed_legacy_root(tmp_path)
    database = Database(f"sqlite:///{tmp_path / 'data' / 'intelligence.db'}")
    database.create_schema()
    repository = SqlAlchemyIntelligenceRepository(database)

    import_legacy_state(tmp_path, repository)

    transitions = repository.list_lifecycle_transitions(
        "release:legacy:sample-8b"
    )
    assert [(row.from_state, row.to_state) for row in transitions] == [
        (LifecycleState.DETECTED, LifecycleState.VERIFIED)
    ]
    assert transitions[0].evidence_ids == [
        "evidence:legacy:model-seed:sample-8b"
    ]


def test_import_repairs_missing_transition_for_existing_verified_release(
    tmp_path: Path,
) -> None:
    seed_legacy_root(tmp_path)
    database = Database(f"sqlite:///{tmp_path / 'data' / 'intelligence.db'}")
    database.create_schema()
    repository = SqlAlchemyIntelligenceRepository(database)

    import_legacy_state(tmp_path, repository)
    with database.session() as session:
        session.execute(delete(LifecycleTransitionRow))

    assert repository.get_release_required(
        "release:legacy:sample-8b"
    ).lifecycle is LifecycleState.VERIFIED
    assert repository.list_lifecycle_transitions(
        "release:legacy:sample-8b"
    ) == []

    import_legacy_state(tmp_path, repository)
    import_legacy_state(tmp_path, repository)

    transitions = repository.list_lifecycle_transitions(
        "release:legacy:sample-8b"
    )
    assert [(row.from_state, row.to_state) for row in transitions] == [
        (LifecycleState.DETECTED, LifecycleState.VERIFIED)
    ]


def test_import_preserves_operational_platform_reverification(tmp_path: Path) -> None:
    seed_legacy_root(tmp_path)
    database = Database(f"sqlite:///{tmp_path / 'data' / 'intelligence.db'}")
    database.create_schema()
    repository = SqlAlchemyIntelligenceRepository(database)
    import_legacy_state(tmp_path, repository)
    refreshed_at = datetime(2026, 7, 31, tzinfo=UTC)
    evidence = EvidenceObservation(
        id="evidence:platform:refresh",
        source_url="https://github.com/acme/sample-engine",
        strength=EvidenceStrength.OFFICIAL_DOCUMENTATION,
        retrieved_at=refreshed_at,
        checksum="sha256:fresh",
        extractor_version="test",
    )
    repository.append_evidence(evidence)
    repository.record_platform_verification(
        "platform:legacy:sample-engine",
        refreshed_at,
        evidence_id=evidence.id,
        success=True,
    )

    import_legacy_state(tmp_path, repository)

    claims = repository.list_claims_for_subject(
        "platform:legacy:sample-engine"
    )
    assert claims
    assert all(claim.observed_at == refreshed_at for claim in claims)
    assert all(evidence.id in claim.evidence_ids for claim in claims)


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


def test_reimport_after_seed_edit_appends_content_addressed_evidence(
    tmp_path: Path,
) -> None:
    """Production repro: adding benchmarks to a seed must not break re-import.

    Evidence rows are immutable; a curated-seed edit therefore appends a
    checksum-suffixed row (the platform-import pattern) instead of raising
    RepositoryConflict, and value-identical claims are left untouched.
    """
    seed_legacy_root(tmp_path)
    database = Database(f"sqlite:///{tmp_path / 'data' / 'intelligence.db'}")
    database.create_schema()
    repository = SqlAlchemyIntelligenceRepository(database)
    import_legacy_state(tmp_path, repository)

    (tmp_path / "config" / "model-seed.yaml").write_text(
        MODEL_SEED
        + "    benchmarks:\n"
        + "      - {name: mmlu-pro, score: 61.0, "
        + "source_url: 'https://example.com/card'}\n",
        encoding="utf-8",
    )
    report = import_legacy_state(tmp_path, repository)

    assert report.models_imported == 0  # same release, no duplicate
    base = repository.get_evidence("evidence:legacy:model-seed:sample-8b")
    assert base is not None  # the historical row is retained, immutable
    evidence_ids = {
        evidence_id
        for claim in repository.list_claims_for_subject("release:legacy:sample-8b")
        for evidence_id in claim.evidence_ids
    }
    # Claims stayed on their stored rows; nothing conflicted.
    assert "evidence:legacy:model-seed:sample-8b" in evidence_ids
    # A third import with the edited seed is also stable.
    import_legacy_state(tmp_path, repository)


def test_migrate_amnesties_volatile_conflict_backlog(tmp_path: Path) -> None:
    """The amnesty rides the unconditional rebuild step: qualification
    leases only once per day, so hooking it there left the backlog
    untouched for a whole window (2026-08-05)."""
    from datetime import UTC, datetime

    from radar.intelligence.contracts import ReviewException

    seed_legacy_root(tmp_path)
    database = Database(f"sqlite:///{tmp_path / 'data' / 'intelligence.db'}")
    database.create_schema()
    repository = SqlAlchemyIntelligenceRepository(database)
    repository.open_review_exception(
        ReviewException(
            id="review:flood:legacy",
            subject_id="release:legacy:sample-8b",
            code="conflicting_authoritative_claims",
            message="Authoritative evidence conflicts for: downloads, sha",
            evidence_ids=["evidence:x"],
            opened_at=datetime(2026, 8, 4, tzinfo=UTC),
        )
    )

    report = import_legacy_state(tmp_path, repository)

    assert report.volatile_reviews_amnestied == 1
    review = repository.get_review_exception("review:flood:legacy")
    assert review is not None and review.resolved_at is not None
    # Second rebuild: nothing left to drain.
    assert import_legacy_state(tmp_path, repository).volatile_reviews_amnestied == 0


def test_migrate_amnesties_collection_card_lineage_reviews(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from radar.intelligence.contracts import ReviewException

    seed_legacy_root(tmp_path)
    database = Database(f"sqlite:///{tmp_path / 'data' / 'intelligence.db'}")
    database.create_schema()
    repository = SqlAlchemyIntelligenceRepository(database)
    many = ", ".join(f"hf:org/model-{i}" for i in range(6))
    repository.open_review_exception(
        ReviewException(
            id="review:lineage:collection",
            subject_id="release:provisional:x",
            code="lineage-conflict",
            message=f"Conflicting lineage parents declared: {many}",
            evidence_ids=["evidence:x"],
            opened_at=datetime(2026, 8, 4, tzinfo=UTC),
        )
    )
    repository.open_review_exception(
        ReviewException(
            id="review:lineage:real",
            subject_id="release:provisional:y",
            code="lineage-conflict",
            message="Conflicting lineage parents declared: hf:a/one, hf:b/two",
            evidence_ids=["evidence:y"],
            opened_at=datetime(2026, 8, 4, tzinfo=UTC),
        )
    )

    import_legacy_state(tmp_path, repository)

    collection = repository.get_review_exception("review:lineage:collection")
    assert collection is not None and collection.resolved_at is not None
    real = repository.get_review_exception("review:lineage:real")
    assert real is not None and real.resolved_at is None
