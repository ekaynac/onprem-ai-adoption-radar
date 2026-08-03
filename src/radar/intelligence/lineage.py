"""Lineage edge building and deterministic, cycle-safe root resolution.

Pure functions over ``LineageEdge`` values plus a thin ``LineageService``
that persists edges, re-resolves declared parents against the canonical
release namespace, and opens scoped review exceptions for findings.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from radar.intelligence.contracts import (
    LineageEdge,
    LineageRelation,
    LineageReviewStatus,
    Release,
    ReviewException,
)


LINEAGE_EXTRACTOR_VERSION = "hf-lineage-v1"

REVIEW_CODE_CONFLICT = "lineage-conflict"
REVIEW_CODE_UNRESOLVED_PARENT = "lineage-unresolved-parent"
REVIEW_CODE_CYCLE = "lineage-cycle"

DECLARED_CONFIDENCE = {
    "api": 0.95,
    "tags": 0.9,
    "card": 0.85,
}
DEFAULT_DECLARED_CONFIDENCE = 0.85

_RELATIONS_BY_DECLARED = {relation.value: relation for relation in LineageRelation}


def relation_from_declared(value: Any) -> LineageRelation:
    """Map a declared relation string to the canonical enum.

    A bare ``base_model:X`` declaration carries no relation qualifier; it
    asserts only "X is my base", which is exactly ``LineageRelation.BASE`` —
    we never guess a more specific derivation.
    """
    if isinstance(value, str):
        relation = _RELATIONS_BY_DECLARED.get(value.strip().casefold())
        if relation is not None:
            return relation
    return LineageRelation.BASE


def parent_external_ref(parent_repo: str) -> str:
    return f"hf:{parent_repo}"


def edge_id(
    child_release_id: str,
    relation: LineageRelation,
    parent_ref: str,
) -> str:
    return f"lineage:{child_release_id}:{relation.value}:{parent_ref.casefold()}"


def build_edges(
    child_release_id: str,
    declared: Any,
    *,
    resolve_parent: Callable[[str], str | None],
    evidence_ids: Sequence[str],
    observed_at: datetime,
) -> list[LineageEdge]:
    """Build declared edges from a ``lineage_declared`` claim value."""
    if not isinstance(declared, list):
        return []
    edges: dict[str, LineageEdge] = {}
    for entry in declared:
        if not isinstance(entry, dict):
            continue
        parent_repo = entry.get("parent_repo")
        if not isinstance(parent_repo, str) or "/" not in parent_repo:
            continue
        relation = relation_from_declared(entry.get("relation"))
        via = entry.get("via")
        parent_ref = parent_external_ref(parent_repo)
        parent_release_id = resolve_parent(parent_repo)
        if parent_release_id == child_release_id:
            continue
        identifier = edge_id(child_release_id, relation, parent_ref)
        edges.setdefault(
            identifier,
            LineageEdge(
                id=identifier,
                child_release_id=child_release_id,
                parent_external_ref=parent_ref,
                parent_release_id=parent_release_id,
                relation=relation,
                declared=True,
                confidence=DECLARED_CONFIDENCE.get(
                    via if isinstance(via, str) else "",
                    DEFAULT_DECLARED_CONFIDENCE,
                ),
                evidence_ids=list(evidence_ids),
                extractor_version=LINEAGE_EXTRACTOR_VERSION,
                observed_at=observed_at,
            ),
        )
    return [edges[key] for key in sorted(edges)]


@dataclass(frozen=True)
class LineageReviewFinding:
    subject_id: str
    code: str
    message: str


@dataclass(frozen=True)
class RootResolutionResult:
    roots: dict[str, str | None]
    edges: list[LineageEdge]
    findings: list[LineageReviewFinding] = field(default_factory=list)


def resolve_roots(edges: Sequence[LineageEdge]) -> RootResolutionResult:
    """Resolve every child's root release deterministically.

    - A node without outgoing edges is its own root.
    - Merges (or any multi-parent set that is all-merge) root at the child.
    - Distinct non-merge parents conflict: root unknown, review opened.
    - An unresolved parent breaks the chain: root unknown, review opened —
      an unknown stays unknown rather than becoming a wrong ancestor.
    - Cycles root at the child and open a review.
    """
    by_child: dict[str, list[LineageEdge]] = {}
    for edge in edges:
        by_child.setdefault(edge.child_release_id, []).append(edge)

    roots: dict[str, str | None] = {}
    findings: dict[tuple[str, str], LineageReviewFinding] = {}

    def add_finding(subject_id: str, code: str, message: str) -> None:
        findings.setdefault(
            (subject_id, code),
            LineageReviewFinding(subject_id=subject_id, code=code, message=message),
        )

    def resolve(node: str, visiting: tuple[str, ...]) -> str | None:
        if node in roots:
            return roots[node]
        if node in visiting:
            add_finding(
                node,
                REVIEW_CODE_CYCLE,
                "Lineage cycle detected: " + " -> ".join((*visiting, node)),
            )
            roots[node] = node
            return node
        node_edges = by_child.get(node)
        if not node_edges:
            roots[node] = node
            return node
        distinct_parents = sorted(
            {
                edge.parent_release_id or edge.parent_external_ref
                for edge in node_edges
            }
        )
        if len(distinct_parents) > 1:
            if all(
                edge.relation is LineageRelation.MERGE for edge in node_edges
            ):
                roots[node] = node
                return node
            add_finding(
                node,
                REVIEW_CODE_CONFLICT,
                "Conflicting lineage parents declared: "
                + ", ".join(distinct_parents),
            )
            roots[node] = None
            return None
        primary = max(
            node_edges,
            key=lambda edge: (
                edge.confidence,
                edge.parent_release_id or "",
                edge.id,
            ),
        )
        if primary.parent_release_id is None:
            add_finding(
                node,
                REVIEW_CODE_UNRESOLVED_PARENT,
                "Declared lineage parent is not resolvable: "
                f"{primary.parent_external_ref}",
            )
            roots[node] = None
            return None
        root = resolve(primary.parent_release_id, (*visiting, node))
        roots[node] = root
        return root

    for child in sorted(by_child):
        resolve(child, ())

    updated: list[LineageEdge] = []
    for edge in sorted(edges, key=lambda item: item.id):
        child_root = roots.get(edge.child_release_id)
        has_finding = any(
            subject_id == edge.child_release_id
            for subject_id, _ in findings
        )
        if edge.review_status is LineageReviewStatus.RESOLVED:
            review_status = LineageReviewStatus.RESOLVED
        elif has_finding:
            review_status = LineageReviewStatus.OPEN
        else:
            review_status = LineageReviewStatus.CLEAR
        updated.append(
            edge.model_copy(
                update={
                    "root_release_id": child_root,
                    "review_status": review_status,
                }
            )
        )
    return RootResolutionResult(
        roots=roots,
        edges=updated,
        findings=[findings[key] for key in sorted(findings)],
    )


class LineageRepository(Protocol):
    def upsert_lineage_edge(self, edge: LineageEdge) -> bool: ...

    def list_all_lineage_edges(self) -> list[LineageEdge]: ...

    def list_all_releases(self) -> list[Release]: ...

    def latest_claim_values(
        self,
        subject_ids: list[str],
        predicates: set[str],
    ) -> dict[str, dict[str, Any]]: ...

    def open_review_exception(self, review: ReviewException) -> None: ...

    def get_review_exception(
        self,
        exception_id: str,
    ) -> ReviewException | None: ...


class LineageService:
    """Persist declared lineage and keep parent/root resolution current."""

    def __init__(self, repository: LineageRepository):
        self.repository = repository
        self._repo_map: dict[str, str] | None = None

    def hf_repo_release_map(self) -> dict[str, str]:
        """Map casefolded HF repo ids to canonical release ids (one query)."""
        if self._repo_map is None:
            release_ids = [
                release.id for release in self.repository.list_all_releases()
            ]
            values = self.repository.latest_claim_values(
                release_ids,
                {"hf_repo", "repo_id"},
            )
            repo_map: dict[str, str] = {}
            for release_id, claims in values.items():
                for predicate in ("hf_repo", "repo_id"):
                    repo = claims.get(predicate)
                    if isinstance(repo, str) and "/" in repo:
                        repo_map.setdefault(repo.casefold(), release_id)
            self._repo_map = repo_map
        return self._repo_map

    def resolve_parent(self, parent_repo: str) -> str | None:
        return self.hf_repo_release_map().get(parent_repo.casefold())

    def ingest_declared(
        self,
        child_release_id: str,
        declared: Any,
        *,
        evidence_ids: Sequence[str],
        observed_at: datetime,
    ) -> int:
        """Upsert edges for one release's ``lineage_declared`` claim value."""
        edges = build_edges(
            child_release_id,
            declared,
            resolve_parent=self.resolve_parent,
            evidence_ids=evidence_ids,
            observed_at=observed_at,
        )
        changed = 0
        for edge in edges:
            existing = None
            get_edge = getattr(self.repository, "get_lineage_edge", None)
            if get_edge is not None:
                existing = get_edge(edge.id)
            if existing is not None:
                # Preserve resolution state; refresh declaration facts only.
                edge = edge.model_copy(
                    update={
                        "parent_release_id": existing.parent_release_id
                        or edge.parent_release_id,
                        "root_release_id": existing.root_release_id,
                        "review_status": existing.review_status,
                    }
                )
            if self.repository.upsert_lineage_edge(edge):
                changed += 1
        return changed

    def sync_roots(self, now: datetime) -> RootResolutionResult:
        """Re-resolve parents and roots for every stored edge."""
        edges = self.repository.list_all_lineage_edges()
        refreshed: list[LineageEdge] = []
        for edge in edges:
            if edge.parent_release_id is None:
                parent_repo = edge.parent_external_ref.removeprefix("hf:")
                resolved = self.resolve_parent(parent_repo)
                if resolved is not None and resolved != edge.child_release_id:
                    edge = edge.model_copy(
                        update={"parent_release_id": resolved}
                    )
            refreshed.append(edge)
        result = resolve_roots(refreshed)
        for edge in result.edges:
            self.repository.upsert_lineage_edge(edge)
        evidence_by_child: dict[str, list[str]] = {}
        for edge in result.edges:
            evidence_by_child.setdefault(edge.child_release_id, []).extend(
                edge.evidence_ids
            )
        for finding in result.findings:
            digest = hashlib.sha256(
                f"{finding.subject_id}|{finding.code}".encode()
            ).hexdigest()
            review_id = f"review:lineage:{digest}"
            if self.repository.get_review_exception(review_id) is not None:
                continue
            self.repository.open_review_exception(
                ReviewException(
                    id=review_id,
                    subject_id=finding.subject_id,
                    code=finding.code,
                    message=finding.message,
                    evidence_ids=sorted(
                        set(evidence_by_child.get(finding.subject_id, []))
                    ),
                    opened_at=now,
                )
            )
        return result
