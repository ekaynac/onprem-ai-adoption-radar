"""Deterministic clustering of cross-source release candidates."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from radar.intelligence.identity import IdentityResolver, normalize_identity
from radar.intelligence.sources.base import DiscoveryCandidate


@dataclass(frozen=True)
class CandidateCluster:
    id: str
    canonical_release_id: str | None
    candidates: tuple[DiscoveryCandidate, ...]
    conflict_claims: tuple[str, ...] = ()
    review_code: str | None = None


def cluster_candidates(
    candidates: list[DiscoveryCandidate],
    resolver: IdentityResolver,
) -> list[CandidateCluster]:
    grouped: dict[str, list[tuple[DiscoveryCandidate, str | None]]] = {}
    for candidate in candidates:
        resolution = resolver.resolve(candidate)
        if resolution.release_id is not None:
            key = f"release:{resolution.release_id}"
        elif resolution.publisher_id is not None:
            key = (
                f"new:{resolution.publisher_id}:"
                f"{normalize_identity(candidate.release_name)}"
            )
        else:
            key = (
                f"review:{candidate.source_record.source_id}:"
                f"{candidate.external_id}"
            )
        grouped.setdefault(key, []).append(
            (candidate, resolution.review_code)
        )

    clusters: list[CandidateCluster] = []
    for _key, items in grouped.items():
        ordered = tuple(
            sorted(
                (candidate for candidate, _review_code in items),
                key=lambda candidate: (
                    candidate.source_record.source_id,
                    candidate.external_id.casefold(),
                ),
            )
        )
        resolution = resolver.resolve(ordered[0])
        cluster_id = _cluster_id(ordered)
        categories = {
            candidate.category_hint
            for candidate in ordered
            if candidate.category_hint is not None
        }
        conflict_claims = (
            ("category_hint",) if len(categories) > 1 else ()
        )
        review_codes = {
            code for _candidate, code in items if code is not None
        }
        clusters.append(
            CandidateCluster(
                id=cluster_id,
                canonical_release_id=resolution.release_id,
                candidates=ordered,
                conflict_claims=conflict_claims,
                review_code=(
                    sorted(review_codes)[0] if review_codes else None
                ),
            )
        )
    return sorted(clusters, key=lambda cluster: cluster.id)


def _cluster_id(candidates: tuple[DiscoveryCandidate, ...]) -> str:
    identity = "\n".join(
        f"{candidate.source_record.source_id}:{candidate.external_id}"
        for candidate in candidates
    )
    return f"cluster:{hashlib.sha256(identity.encode()).hexdigest()}"
