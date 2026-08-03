from __future__ import annotations

import pytest
from pydantic import ValidationError

from radar.intelligence.contracts import (
    LineageEdge,
    LineageRelation,
    LineageReviewStatus,
)
from radar.intelligence.repositories import RepositoryConflict

from .lifecycle_helpers import NOW, RELEASE_ID, lifecycle_repository


def make_edge(**overrides: object) -> LineageEdge:
    values: dict[str, object] = {
        "id": f"lineage:{RELEASE_ID}:quantized:hf:moonshotai/kimi-k3",
        "child_release_id": RELEASE_ID,
        "parent_external_ref": "hf:moonshotai/Kimi-K3",
        "relation": LineageRelation.QUANTIZED,
        "declared": True,
        "confidence": 0.95,
        "evidence_ids": ["evidence:hf:base-models"],
        "extractor_version": "lineage-v1",
        "observed_at": NOW,
    }
    values.update(overrides)
    return LineageEdge.model_validate(values)


def test_declared_edge_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="require evidence"):
        make_edge(evidence_ids=[])


def test_inferred_edge_without_evidence_is_allowed() -> None:
    edge = make_edge(declared=False, evidence_ids=[], confidence=0.4)
    assert edge.review_status is LineageReviewStatus.CLEAR


def test_release_cannot_be_its_own_parent() -> None:
    with pytest.raises(ValidationError, match="own lineage parent"):
        make_edge(parent_release_id=RELEASE_ID)


def test_upsert_is_idempotent(tmp_path) -> None:
    repo = lifecycle_repository(tmp_path)
    edge = make_edge()

    assert repo.upsert_lineage_edge(edge) is True
    assert repo.upsert_lineage_edge(edge) is False
    assert repo.get_lineage_edge(edge.id) == edge
    assert repo.count_lineage_edges() == 1


def test_resolution_updates_overwrite_in_place(tmp_path) -> None:
    repo = lifecycle_repository(tmp_path)
    edge = make_edge()
    repo.upsert_lineage_edge(edge)

    resolved = make_edge(
        parent_release_id="release:moonshot-ai:kimi:k3:base",
        root_release_id="release:moonshot-ai:kimi:k3:base",
        review_status=LineageReviewStatus.RESOLVED,
    )
    assert repo.upsert_lineage_edge(resolved) is True
    stored = repo.get_lineage_edge(edge.id)
    assert stored is not None
    assert stored.parent_release_id == "release:moonshot-ai:kimi:k3:base"
    assert stored.root_release_id == "release:moonshot-ai:kimi:k3:base"
    assert stored.review_status is LineageReviewStatus.RESOLVED


def test_identity_change_under_existing_id_is_rejected(tmp_path) -> None:
    repo = lifecycle_repository(tmp_path)
    repo.upsert_lineage_edge(make_edge())

    with pytest.raises(RepositoryConflict, match="Lineage edge id reused"):
        repo.upsert_lineage_edge(
            make_edge(parent_external_ref="hf:other/parent")
        )


def test_list_for_child_and_children_and_unresolved(tmp_path) -> None:
    repo = lifecycle_repository(tmp_path)
    unresolved = make_edge()
    resolved = make_edge(
        id=f"lineage:{RELEASE_ID}:finetune:hf:qwen/qwen3-8b",
        parent_external_ref="hf:Qwen/Qwen3-8B",
        relation=LineageRelation.FINETUNE,
        parent_release_id="release:qwen:qwen3:8b",
        root_release_id="release:qwen:qwen3:8b",
    )
    repo.upsert_lineage_edge(unresolved)
    repo.upsert_lineage_edge(resolved)

    assert {e.id for e in repo.list_lineage_for_child(RELEASE_ID)} == {
        unresolved.id,
        resolved.id,
    }
    assert [e.id for e in repo.list_lineage_children("release:qwen:qwen3:8b")] == [
        resolved.id
    ]
    assert [e.id for e in repo.list_unresolved_lineage()] == [unresolved.id]
    assert len(repo.list_all_lineage_edges()) == 2
