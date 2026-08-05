from __future__ import annotations

from datetime import UTC, datetime

from radar.intelligence.contracts import (
    LineageEdge,
    LineageRelation,
    LineageReviewStatus,
)
from radar.intelligence.lineage import (
    LINEAGE_EXTRACTOR_VERSION,
    REVIEW_CODE_CONFLICT,
    REVIEW_CODE_CYCLE,
    REVIEW_CODE_UNRESOLVED_PARENT,
    build_edges,
    relation_from_declared,
    resolve_roots,
)


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def make_edge(
    child: str,
    parent_ref: str,
    *,
    parent: str | None = None,
    relation: LineageRelation = LineageRelation.QUANTIZED,
    confidence: float = 0.9,
    review_status: LineageReviewStatus = LineageReviewStatus.CLEAR,
) -> LineageEdge:
    return LineageEdge(
        id=f"lineage:{child}:{relation.value}:{parent_ref.casefold()}",
        child_release_id=child,
        parent_external_ref=parent_ref,
        parent_release_id=parent,
        relation=relation,
        declared=False,
        confidence=confidence,
        extractor_version=LINEAGE_EXTRACTOR_VERSION,
        review_status=review_status,
        observed_at=NOW,
    )


def test_relation_mapping_never_guesses() -> None:
    assert relation_from_declared("quantized") is LineageRelation.QUANTIZED
    assert relation_from_declared("Finetune") is LineageRelation.FINETUNE
    assert relation_from_declared(None) is LineageRelation.BASE
    assert relation_from_declared("something-new") is LineageRelation.BASE


def test_build_edges_from_declared_claim() -> None:
    resolved = {"moonshotai/Kimi-K3": "release:moonshot-ai:kimi:k3"}
    edges = build_edges(
        "release:grearl:kimi:k3:gguf",
        [
            {
                "parent_repo": "moonshotai/Kimi-K3",
                "relation": "quantized",
                "via": "api",
            },
            {"parent_repo": "unknown/Parent", "relation": None, "via": "card"},
            {"parent_repo": "not-a-repo", "relation": "finetune", "via": "tags"},
        ],
        resolve_parent=resolved.get,
        evidence_ids=["evidence:hf:metadata"],
        observed_at=NOW,
    )

    assert [
        (
            edge.parent_external_ref,
            edge.relation,
            edge.parent_release_id,
            edge.confidence,
        )
        for edge in edges
    ] == [
        ("hf:unknown/Parent", LineageRelation.BASE, None, 0.85),
        (
            "hf:moonshotai/Kimi-K3",
            LineageRelation.QUANTIZED,
            "release:moonshot-ai:kimi:k3",
            0.95,
        ),
    ]
    assert all(edge.declared for edge in edges)
    assert all(edge.evidence_ids == ["evidence:hf:metadata"] for edge in edges)


def test_build_edges_skips_self_reference() -> None:
    edges = build_edges(
        "release:acme:model",
        [{"parent_repo": "acme/Model", "relation": "quantized", "via": "tags"}],
        resolve_parent=lambda _: "release:acme:model",
        evidence_ids=["evidence:x"],
        observed_at=NOW,
    )
    assert edges == []


def test_chain_resolves_transitively_to_root() -> None:
    edges = [
        make_edge("release:c", "hf:b/repo", parent="release:b"),
        make_edge(
            "release:b",
            "hf:a/repo",
            parent="release:a",
            relation=LineageRelation.FINETUNE,
        ),
    ]

    result = resolve_roots(edges)

    assert result.roots == {
        "release:c": "release:a",
        "release:b": "release:a",
        "release:a": "release:a",
    }
    assert result.findings == []
    assert all(
        edge.root_release_id == "release:a"
        and edge.review_status is LineageReviewStatus.CLEAR
        for edge in result.edges
    )


def test_all_merge_parents_root_at_the_child() -> None:
    edges = [
        make_edge(
            "release:merged",
            "hf:a/repo",
            parent="release:a",
            relation=LineageRelation.MERGE,
        ),
        make_edge(
            "release:merged",
            "hf:b/repo",
            parent="release:b",
            relation=LineageRelation.MERGE,
        ),
    ]

    result = resolve_roots(edges)

    assert result.roots["release:merged"] == "release:merged"
    assert result.findings == []


def test_conflicting_non_merge_parents_open_review() -> None:
    edges = [
        make_edge(
            "release:child",
            "hf:a/repo",
            parent="release:a",
            relation=LineageRelation.FINETUNE,
        ),
        make_edge(
            "release:child",
            "hf:b/repo",
            parent="release:b",
            relation=LineageRelation.QUANTIZED,
        ),
    ]

    result = resolve_roots(edges)

    assert result.roots["release:child"] is None
    assert [finding.code for finding in result.findings] == [REVIEW_CODE_CONFLICT]
    assert all(
        edge.review_status is LineageReviewStatus.OPEN for edge in result.edges
    )


def test_unresolved_parent_keeps_root_unknown() -> None:
    edges = [make_edge("release:child", "hf:ghost/repo", parent=None)]

    result = resolve_roots(edges)

    assert result.roots["release:child"] is None
    assert [finding.code for finding in result.findings] == [
        REVIEW_CODE_UNRESOLVED_PARENT
    ]
    assert result.edges[0].root_release_id is None
    assert result.edges[0].review_status is LineageReviewStatus.OPEN


def test_cycle_is_detected_and_rooted_deterministically() -> None:
    edges = [
        make_edge("release:a", "hf:b/repo", parent="release:b"),
        make_edge("release:b", "hf:a/repo", parent="release:a"),
    ]

    result = resolve_roots(edges)

    assert [finding.code for finding in result.findings] == [REVIEW_CODE_CYCLE]
    assert result.roots["release:a"] == "release:a"
    assert result.roots["release:b"] == "release:a"


def test_operator_resolved_status_is_preserved() -> None:
    edges = [
        make_edge(
            "release:child",
            "hf:ghost/repo",
            parent=None,
            review_status=LineageReviewStatus.RESOLVED,
        )
    ]

    result = resolve_roots(edges)

    assert result.edges[0].review_status is LineageReviewStatus.RESOLVED


def test_highest_confidence_edge_wins_tie_break() -> None:
    edges = [
        make_edge(
            "release:child",
            "hf:base/repo",
            parent="release:base",
            relation=LineageRelation.BASE,
            confidence=0.85,
        ),
        make_edge(
            "release:child",
            "hf:base/repo",
            parent="release:base",
            relation=LineageRelation.QUANTIZED,
            confidence=0.95,
        ),
    ]

    result = resolve_roots(edges)

    assert result.roots["release:child"] == "release:base"
    assert result.findings == []


def test_name_inference_matches_exactly_one_indexed_parent():
    from radar.intelligence.lineage import infer_name_parent

    index = {
        "acme/model-x": "acme/Model-X",
        "other/model-y": "other/Model-Y",
    }
    inferred = infer_name_parent("quantco/Model-X-GGUF", index)
    assert inferred is not None
    parent, relation = inferred
    assert parent == "acme/Model-X"
    assert relation.value == "quantized"
    # Ambiguity → None (two candidates carry the stem).
    ambiguous = {
        "a/model-x": "a/Model-X",
        "b/model-x": "b/Model-X",
    }
    assert infer_name_parent("q/Model-X-AWQ", ambiguous) is None
    # No known suffix → None; self-match → None.
    assert infer_name_parent("acme/Model-X", index) is None
    assert (
        infer_name_parent("acme/Model-X-GGUF", {"acme/model-x-gguf": "acme/Model-X-GGUF"})
        is None
    )


def test_collection_cards_produce_no_edges_and_no_conflict():
    from datetime import UTC, datetime

    from radar.intelligence.lineage import build_edges

    declared = [
        {"parent_repo": f"org/model-{index}", "relation": "base", "via": "card"}
        for index in range(6)
    ]
    edges = build_edges(
        "release:child",
        declared,
        resolve_parent=lambda repo: None,
        evidence_ids=["evidence:x"],
        observed_at=datetime(2026, 8, 5, tzinfo=UTC),
    )
    assert edges == []


def test_legacy_collection_edges_self_root_without_finding():
    from datetime import UTC, datetime

    from radar.intelligence.contracts import LineageEdge, LineageRelation
    from radar.intelligence.lineage import resolve_roots

    edges = [
        LineageEdge(
            id=f"lineage:release:child:base:hf:org/m{index}",
            child_release_id="release:child",
            parent_external_ref=f"hf:org/m{index}",
            relation=LineageRelation.BASE,
            declared=True,
            confidence=0.85,
            evidence_ids=["evidence:card"],
            extractor_version="hf-lineage-v1",
            observed_at=datetime(2026, 8, 5, tzinfo=UTC),
        )
        for index in range(5)
    ]
    result = resolve_roots(edges)
    assert result.roots["release:child"] == "release:child"
    assert result.findings == []


def test_undeclared_inferred_edges_never_set_roots():
    from datetime import UTC, datetime

    from radar.intelligence.contracts import LineageEdge, LineageRelation
    from radar.intelligence.lineage import resolve_roots

    inferred = LineageEdge(
        id="lineage:release:child:quantized:hf:acme/model-x",
        child_release_id="release:child",
        parent_external_ref="hf:acme/model-x",
        parent_release_id="release:parent",
        relation=LineageRelation.QUANTIZED,
        declared=False,
        confidence=0.5,
        extractor_version="hf-lineage-name-v1",
        observed_at=datetime(2026, 8, 5, tzinfo=UTC),
    )
    result = resolve_roots([inferred])
    # The suggestion exists as data, but ancestry is not auto-accepted.
    assert result.roots["release:child"] == "release:child"
    assert result.findings == []


def test_suggestion_accept_promotes_and_reroots(tmp_path):
    from datetime import UTC, datetime

    import pytest

    from radar.intelligence.contracts import (
        EvidenceStrength,
        LifecycleState,
        LineageRelation,
        ModelCategory,
        Release,
        ReleaseLane,
    )
    from radar.intelligence.lineage import (
        SuggestionError,
        accept_suggestion,
        build_inferred_edge,
        list_suggestions,
        reject_suggestion,
    )

    from .lifecycle_helpers import lifecycle_repository

    repository = lifecycle_repository(tmp_path)
    now = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    for release_id in ("release:child", "release:child2"):
        repository.upsert_release(
            Release(
                id=release_id,
                family_id="family:moonshot-ai:kimi",
                publisher_id="publisher:moonshot-ai",
                name=release_id,
                category=ModelCategory.TEXT_REASONING,
                lane=ReleaseLane.DEPLOYABLE,
                lifecycle=LifecycleState.DETECTED,
                first_observed_at=now,
                discovery_evidence_strength=EvidenceStrength.TRUSTED_REGISTRY,
            )
        )
    edge = build_inferred_edge(
        "release:child",
        "quantco/Model-X-GGUF",
        "acme/Model-X",
        LineageRelation.QUANTIZED,
        resolve_parent=lambda repo: None,
        observed_at=now,
    )
    repository.upsert_lineage_edge(edge)
    assert [e.id for e in list_suggestions(repository)] == [edge.id]

    accepted = accept_suggestion(repository, edge.id, now)

    assert accepted.declared is True
    assert accepted.confidence == 0.9
    assert accepted.evidence_ids  # the confirmation act is the evidence
    assert list_suggestions(repository) == []
    # Accepting again fails: it is no longer a suggestion.
    with pytest.raises(SuggestionError):
        accept_suggestion(repository, edge.id, now)

    # Reject path: a second suggestion disappears entirely.
    other = build_inferred_edge(
        "release:child2",
        "q/Model-Y-AWQ",
        "acme/Model-Y",
        LineageRelation.QUANTIZED,
        resolve_parent=lambda repo: None,
        observed_at=now,
    )
    repository.upsert_lineage_edge(other)
    reject_suggestion(repository, other.id)
    assert repository.get_lineage_edge(other.id) is None
    with pytest.raises(SuggestionError):
        reject_suggestion(repository, other.id)


def test_list_suggestions_orders_for_triage(tmp_path):
    """Strongest confidence first, then relation, then child id."""
    from radar.intelligence.contracts import (
        EvidenceStrength,
        LifecycleState,
        LineageRelation,
        ModelCategory,
        Release,
        ReleaseLane,
    )
    from radar.intelligence.lineage import build_inferred_edge, list_suggestions

    from .lifecycle_helpers import lifecycle_repository

    repository = lifecycle_repository(tmp_path)
    now = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    for release_id in ("release:a", "release:b", "release:c"):
        repository.upsert_release(
            Release(
                id=release_id,
                family_id="family:moonshot-ai:kimi",
                publisher_id="publisher:moonshot-ai",
                name=release_id,
                category=ModelCategory.TEXT_REASONING,
                lane=ReleaseLane.DEPLOYABLE,
                lifecycle=LifecycleState.DETECTED,
                first_observed_at=now,
                discovery_evidence_strength=EvidenceStrength.TRUSTED_REGISTRY,
            )
        )
    quant_b = build_inferred_edge(
        "release:b",
        "quantco/Model-B-GGUF",
        "acme/Model-B",
        LineageRelation.QUANTIZED,
        resolve_parent=lambda repo: None,
        observed_at=now,
    )
    quant_a = build_inferred_edge(
        "release:a",
        "quantco/Model-A-AWQ",
        "acme/Model-A",
        LineageRelation.QUANTIZED,
        resolve_parent=lambda repo: None,
        observed_at=now,
    )
    converted_c = build_inferred_edge(
        "release:c",
        "mlxco/Model-C-MLX",
        "acme/Model-C",
        LineageRelation.CONVERTED,
        resolve_parent=lambda repo: None,
        observed_at=now,
    )
    for edge in (quant_b, converted_c, quant_a):
        repository.upsert_lineage_edge(edge)

    ordered = list_suggestions(repository)

    # Same confidence (0.5): relation alphabetical, then child id.
    assert [e.id for e in ordered] == [converted_c.id, quant_a.id, quant_b.id]
