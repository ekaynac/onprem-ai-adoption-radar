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
_LINEAGE_REVIEW_CODES = frozenset(
    {REVIEW_CODE_CONFLICT, REVIEW_CODE_UNRESOLVED_PARENT, REVIEW_CODE_CYCLE}
)


def _lineage_review_id(subject_id: str, code: str) -> str:
    digest = hashlib.sha256(f"{subject_id}|{code}".encode()).hexdigest()
    return f"review:lineage:{digest}"

DECLARED_CONFIDENCE = {
    # Tier-1: registry/author-declared.
    "api": 0.95,
    "tags": 0.9,
    "card": 0.85,
    # Tier-2: artifact-declared (read from the repo's own files).
    "adapter_config": 0.8,
    "config": 0.7,
    # Tier-3: inferred from naming fingerprints — never auto-accepted
    # (see resolve_roots: undeclared edges don't participate in roots).
    "name": 0.5,
}
DEFAULT_DECLARED_CONFIDENCE = 0.85

INFERRED_EXTRACTOR_VERSION = "hf-lineage-name-v1"

# Edges below this confidence are suggestions: stored and visible, but
# they never set roots/grouping until a human confirms the ancestry.
AUTO_ACCEPT_CONFIDENCE = 0.7

# A card declaring this many or more distinct non-merge parents is an
# aggregation/evaluation/collection card, not a lineage statement — no
# edges, no conflict review (the 57-parent audio-model card class).
LINEAGE_COLLECTION_PARENT_THRESHOLD = 5

# Derivative-artifact suffixes that name the parent when stripped
# (order matters: longest-ish, checked case-insensitively).
_NAME_DERIVATIVE_SUFFIXES: tuple[tuple[str, LineageRelation], ...] = (
    ("-gguf", LineageRelation.QUANTIZED),
    ("-awq", LineageRelation.QUANTIZED),
    ("-gptq", LineageRelation.QUANTIZED),
    ("-exl2", LineageRelation.QUANTIZED),
    ("-exl3", LineageRelation.QUANTIZED),
    ("-4bit", LineageRelation.QUANTIZED),
    ("-8bit", LineageRelation.QUANTIZED),
    ("-bnb-4bit", LineageRelation.QUANTIZED),
    ("-fp8", LineageRelation.QUANTIZED),
    ("-nvfp4", LineageRelation.QUANTIZED),
    ("-mlx", LineageRelation.CONVERTED),
    ("-onnx", LineageRelation.CONVERTED),
)


def infer_name_parent(
    child_repo: str,
    index_repos: dict[str, str],
) -> tuple[str, LineageRelation] | None:
    """Tier-3: infer a parent repo from a derivative-name fingerprint.

    Returns (parent_repo, relation) only when stripping a known artifact
    suffix yields the *name part* of exactly one indexed repo — ambiguity
    or zero matches return None. Callers must store the result as an
    UNDECLARED edge; root resolution ignores those until reviewed.
    """
    if "/" not in child_repo:
        return None
    _, name = child_repo.split("/", 1)
    lowered = name.casefold()
    for suffix, relation in _NAME_DERIVATIVE_SUFFIXES:
        if not lowered.endswith(suffix):
            continue
        stem = lowered[: -len(suffix)].rstrip("-_.")
        if not stem:
            return None
        matches = sorted(
            {
                repo
                for repo_key, repo in index_repos.items()
                if repo_key.split("/", 1)[-1] == stem
                and repo.casefold() != child_repo.casefold()
            }
        )
        if len(matches) == 1:
            return matches[0], relation
        return None
    return None


def build_inferred_edge(
    child_release_id: str,
    child_repo: str,
    parent_repo: str,
    relation: LineageRelation,
    *,
    resolve_parent: Callable[[str], str | None],
    observed_at: datetime,
) -> LineageEdge:
    """An undeclared (Tier-3) edge: stored as a suggestion, never a root."""
    parent_ref = parent_external_ref(parent_repo)
    return LineageEdge(
        id=edge_id(child_release_id, relation, parent_ref),
        child_release_id=child_release_id,
        parent_external_ref=parent_ref,
        parent_release_id=resolve_parent(parent_repo),
        relation=relation,
        declared=False,
        confidence=DECLARED_CONFIDENCE["name"],
        evidence_ids=[],
        extractor_version=INFERRED_EXTRACTOR_VERSION,
        observed_at=observed_at,
    )

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
    distinct_parents = {
        entry.get("parent_repo")
        for entry in declared
        if isinstance(entry, dict)
        and isinstance(entry.get("parent_repo"), str)
    }
    non_merge = any(
        isinstance(entry, dict)
        and relation_from_declared(entry.get("relation"))
        is not LineageRelation.MERGE
        for entry in declared
    )
    if len(distinct_parents) >= LINEAGE_COLLECTION_PARENT_THRESHOLD and non_merge:
        # Collection/evaluation card: listing many models is not lineage.
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
    - Sub-threshold edges (confidence < AUTO_ACCEPT_CONFIDENCE, i.e. the
      Tier-3 name fingerprints) never participate: a suggestion is not an
      accepted ancestry — the child stays its own root until a human
      confirms the declaration.
    """
    by_child: dict[str, list[LineageEdge]] = {}
    all_children: set[str] = set()
    for edge in edges:
        all_children.add(edge.child_release_id)
        if edge.confidence < AUTO_ACCEPT_CONFIDENCE:
            continue
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
            if len(distinct_parents) >= LINEAGE_COLLECTION_PARENT_THRESHOLD:
                # Legacy edges from a collection/evaluation card (the guard
                # in build_edges now stops creating these): not lineage,
                # not a conflict worth a human — self-root, no finding.
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
    for child in sorted(all_children - set(roots)):
        # Only suggestion edges: ancestry unconfirmed, child is its own root.
        roots[child] = child

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

    def list_review_exceptions(
        self,
        *,
        open_only: bool = False,
    ) -> list[ReviewException]: ...

    def resolve_review_exception(
        self,
        exception_id: str,
        resolution: str,
        evidence_ids: list[str],
        now: datetime,
    ) -> None: ...


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
        current_review_ids: set[str] = set()
        for finding in result.findings:
            review_id = _lineage_review_id(finding.subject_id, finding.code)
            current_review_ids.add(review_id)
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
        for review in self.repository.list_review_exceptions(open_only=True):
            if review.code not in _LINEAGE_REVIEW_CODES:
                continue
            if not review.id.startswith("review:lineage:"):
                continue
            if review.id in current_review_ids:
                continue
            self.repository.resolve_review_exception(
                review.id,
                "Lineage finding no longer present after re-resolution",
                [],
                now,
            )
        return result
