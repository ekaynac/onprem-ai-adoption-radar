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
