from __future__ import annotations

from radar.intelligence.contracts import ReviewException
from radar.intelligence.review import ReviewService

from .lifecycle_helpers import NOW, RELEASE_ID, lifecycle_repository
from .test_verification import seed_claim


def test_review_resolution_is_append_audited(tmp_path) -> None:
    repository = lifecycle_repository(tmp_path)
    seed_claim(repository, "claim:license:one", "license", "mit", "one")
    seed_claim(
        repository,
        "claim:license:two",
        "license",
        "proprietary",
        "two",
    )
    review = ReviewException(
        id="review:kimi:license",
        subject_id=RELEASE_ID,
        code="conflicting_authoritative_claims",
        message="Official license claims differ",
        evidence_ids=["evidence:one", "evidence:two"],
        opened_at=NOW,
    )
    repository.open_review_exception(review)
    service = ReviewService(repository)

    service.resolve(
        review.id,
        "accept_claim",
        evidence_ids=["evidence:one"],
        now=NOW,
    )

    resolved = repository.get_review_exception(review.id)
    assert resolved is not None
    assert resolved.resolved_at == NOW
    assert repository.get_review_resolution(review.id) == {
        "resolution": "accept_claim",
        "evidence_ids": ["evidence:one"],
    }
    assert repository.get_claim("claim:license:one").state.value == "verified"
    assert repository.get_claim("claim:license:two").state.value == "rejected"


def test_reopening_a_review_is_idempotent_across_runs(tmp_path) -> None:
    """Production repro: the same ambiguous candidate re-encountered on a
    later scan re-opens its identity review with a new timestamp and new
    per-run evidence — that must be a no-op, not a RepositoryConflict.
    A resolved review must also stand (human decisions are never reopened).
    """
    from datetime import UTC, datetime, timedelta

    import pytest

    from radar.intelligence.contracts import ReviewException
    from radar.intelligence.repositories import RepositoryConflict

    repository = lifecycle_repository(tmp_path)
    opened = datetime(2026, 8, 3, 11, 0, tzinfo=UTC)
    first = ReviewException(
        id="review:identity:abc123",
        subject_id="candidate:hf:acme/model",
        code="ambiguous_identity",
        message="Identity review required for Model",
        evidence_ids=["evidence:hf:run-1"],
        opened_at=opened,
    )
    repository.open_review_exception(first)

    # Next scan: same identity, new timestamp + evidence → idempotent.
    repository.open_review_exception(
        first.model_copy(
            update={
                "opened_at": opened + timedelta(hours=2),
                "evidence_ids": ["evidence:hf:run-2"],
            }
        )
    )
    stored = repository.get_review_exception("review:identity:abc123")
    assert stored is not None
    assert stored.opened_at == opened  # first-opened wins
    assert stored.evidence_ids == ["evidence:hf:run-1"]

    # A genuinely different subject under the same id is still a conflict.
    with pytest.raises(RepositoryConflict):
        repository.open_review_exception(
            first.model_copy(update={"subject_id": "candidate:hf:other/model"})
        )


def test_volatile_conflict_amnesty_resolves_only_pure_volatile_rows(
    tmp_path,
) -> None:
    from radar.intelligence.contracts import ReviewException

    repository = lifecycle_repository(tmp_path)

    def _review(review_id: str, code: str, message: str) -> None:
        repository.open_review_exception(
            ReviewException(
                id=review_id,
                subject_id=RELEASE_ID,
                code=code,
                message=message,
                evidence_ids=["evidence:x"],
                opened_at=NOW,
            )
        )

    _review(
        "review:flood:1",
        "conflicting_authoritative_claims",
        "Authoritative evidence conflicts for: downloads, last_modified, sha",
    )
    _review(
        "review:flood:2",
        "conflicting_authoritative_claims",
        "Authoritative evidence conflicts for: likes",
    )
    _review(
        "review:mixed",
        "conflicting_authoritative_claims",
        "Authoritative evidence conflicts for: downloads, license",
    )
    _review(
        "review:other-code",
        "ambiguous_identity",
        "Identity review required for Something",
    )

    resolved = repository.resolve_volatile_conflict_reviews(NOW)

    assert resolved == 2
    flood = repository.get_review_exception("review:flood:1")
    assert flood is not None and flood.resolved_at == NOW
    mixed = repository.get_review_exception("review:mixed")
    assert mixed is not None and mixed.resolved_at is None
    other = repository.get_review_exception("review:other-code")
    assert other is not None and other.resolved_at is None
    # Idempotent — the backlog is drained exactly once.
    assert repository.resolve_volatile_conflict_reviews(NOW) == 0


def test_invalid_parent_ref_purge_deletes_edges_and_reviews(tmp_path) -> None:
    """Filesystem paths in base_model must never survive as lineage."""
    from datetime import UTC, datetime

    from radar.intelligence.contracts import (
        EvidenceStrength,
        LifecycleState,
        LineageEdge,
        LineageRelation,
        ModelCategory,
        Release,
        ReleaseLane,
        ReviewException,
    )

    repository = lifecycle_repository(tmp_path)
    now = datetime(2026, 8, 6, 8, 0, tzinfo=UTC)
    repository.upsert_release(
        Release(
            id="release:child",
            family_id="family:moonshot-ai:kimi",
            publisher_id="publisher:moonshot-ai",
            name="release:child",
            category=ModelCategory.TEXT_REASONING,
            lane=ReleaseLane.DEPLOYABLE,
            lifecycle=LifecycleState.DETECTED,
            first_observed_at=now,
            discovery_evidence_strength=EvidenceStrength.TRUSTED_REGISTRY,
        )
    )
    junk = LineageEdge(
        id="lineage:release:child:base:hf:/root/.cache/torch/thing",
        child_release_id="release:child",
        parent_external_ref="hf:/root/.cache/torch/thing",
        relation=LineageRelation.BASE,
        declared=False,
        confidence=0.5,
        extractor_version="hf-lineage-name-v1",
        observed_at=now,
    )
    good = LineageEdge(
        id="lineage:release:child:quantized:hf:acme/model-x",
        child_release_id="release:child",
        parent_external_ref="hf:acme/Model-X",
        relation=LineageRelation.QUANTIZED,
        declared=False,
        confidence=0.5,
        extractor_version="hf-lineage-name-v1",
        observed_at=now,
    )
    repository.upsert_lineage_edge(junk)
    repository.upsert_lineage_edge(good)
    repository.open_review_exception(
        ReviewException(
            id="review:junk-parent",
            subject_id="release:child",
            code="lineage-unresolved-parent",
            message=(
                "Declared lineage parent is not resolvable: hf:./distil-v3"
            ),
            evidence_ids=[],
            opened_at=now,
        )
    )
    repository.open_review_exception(
        ReviewException(
            id="review:real-parent",
            subject_id="release:child",
            code="lineage-unresolved-parent",
            message=(
                "Declared lineage parent is not resolvable: hf:acme/Gone"
            ),
            evidence_ids=[],
            opened_at=now,
        )
    )

    assert repository.purge_invalid_lineage_parent_refs(now) == 2
    remaining = {e.id for e in repository.list_all_lineage_edges()}
    assert remaining == {good.id}
    junk_review = repository.get_review_exception("review:junk-parent")
    assert junk_review is not None and junk_review.resolved_at == now
    real = repository.get_review_exception("review:real-parent")
    assert real is not None and real.resolved_at is None
    assert repository.purge_invalid_lineage_parent_refs(now) == 0


def test_same_origin_conflict_amnesty_registry_only(tmp_path) -> None:
    from datetime import UTC, datetime

    from radar.intelligence.contracts import (
        EvidenceObservation,
        EvidenceStrength,
        ReviewException,
    )

    repository = lifecycle_repository(tmp_path)
    now = datetime(2026, 8, 6, 8, 0, tzinfo=UTC)

    def _evidence(suffix: str, url: str) -> str:
        evidence = EvidenceObservation(
            id=f"evidence:{suffix}",
            source_url=url,
            strength=EvidenceStrength.TRUSTED_REGISTRY,
            retrieved_at=now,
            checksum=f"sha256:{suffix}",
            extractor_version="test-v1",
        )
        repository.append_evidence(evidence)
        return evidence.id

    hub_list = _evidence(
        "hub-list", "https://huggingface.co/api/models?pipeline_tag=x"
    )
    hub_detail = _evidence(
        "hub-detail",
        "https://huggingface.co/api/models/acme/thing?expand=baseModels",
    )
    docs = _evidence("docs", "https://moonshot.ai/docs/license")

    def _review(review_id: str, evidence_ids: list[str]) -> None:
        repository.open_review_exception(
            ReviewException(
                id=review_id,
                subject_id=RELEASE_ID,
                code="conflicting_authoritative_claims",
                message="Authoritative evidence conflicts for: lineage_declared",
                evidence_ids=evidence_ids,
                opened_at=now,
            )
        )

    _review("review:hub-drift", [hub_list, hub_detail])
    _review("review:cross-origin", [hub_detail, docs])

    assert repository.resolve_same_origin_conflict_reviews(now) == 1
    drift = repository.get_review_exception("review:hub-drift")
    assert drift is not None and drift.resolved_at == now
    cross = repository.get_review_exception("review:cross-origin")
    assert cross is not None and cross.resolved_at is None
    assert repository.resolve_same_origin_conflict_reviews(now) == 0
