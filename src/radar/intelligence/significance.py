"""Deterministic release significance: class before recency, score with receipts.

The published index previously ranked by repository modification time, so a
recently touched zero-download clone outranked the official upstream model.
Significance ranks by *what a release is* first (official root, base,
derivative, provisional) and only then by momentum and completeness within
the class. Every score carries the factor list that produced it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class SignificanceClass(StrEnum):
    OFFICIAL_ROOT = "official_root"
    BASE_RELEASE = "base_release"
    OFFICIAL_PUBLISHER = "official_publisher"
    CURATED = "curated"
    DECLARED_DERIVATIVE = "declared_derivative"
    VERIFIED_DERIVATIVE = "verified_derivative"
    PROVISIONAL = "provisional"


SIGNIFICANCE_RANK: dict[SignificanceClass, int] = {
    significance_class: rank
    for rank, significance_class in enumerate(SignificanceClass)
}

_CURATED_LIFECYCLES = frozenset({"qualified", "recommended"})

_RECENCY_WEIGHT = 0.30
_DOWNLOADS_WEIGHT = 0.25
_CHILDREN_WEIGHT = 0.15
_COMPLETENESS_WEIGHT = 0.15
_LIKES_WEIGHT = 0.10
_CURATED_BONUS = 0.05


@dataclass(frozen=True)
class Significance:
    significance_class: SignificanceClass
    rank: int
    score: float
    factors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "class": self.significance_class.value,
            "rank": self.rank,
            "score": self.score,
            "factors": list(self.factors),
        }


def classify(
    *,
    official: bool,
    lifecycle: str | None,
    curated: bool = False,
    is_root: bool | None = None,
    has_declared_parent: bool = False,
) -> SignificanceClass:
    """First matching class wins; unknown facts never upgrade a release.

    ``is_root`` is tri-state: True (confirmed root — checked with no
    declared parents, or it has resolved children), False (has a parent),
    None (never checked — must not be presented as a base).
    """
    if official and is_root is True:
        return SignificanceClass.OFFICIAL_ROOT
    if is_root is True:
        return SignificanceClass.BASE_RELEASE
    if official:
        return SignificanceClass.OFFICIAL_PUBLISHER
    if curated or (lifecycle in _CURATED_LIFECYCLES):
        return SignificanceClass.CURATED
    if has_declared_parent:
        return SignificanceClass.DECLARED_DERIVATIVE
    if lifecycle == "verified":
        return SignificanceClass.VERIFIED_DERIVATIVE
    return SignificanceClass.PROVISIONAL


def _recency_factor(released_at: datetime | None, now: datetime) -> float:
    if released_at is None:
        return 0.0
    age_days = max((now - released_at).total_seconds() / 86_400.0, 0.0)
    if age_days <= 7:
        return 1.0
    if age_days <= 30:
        return 0.6
    if age_days <= 90:
        return 0.3
    return 0.1


def _log_scale(value: int | None, ceiling_exponent: float) -> float:
    if not value or value <= 0:
        return 0.0
    return min(math.log10(value + 1) / ceiling_exponent, 1.0)


def compute_significance(
    *,
    official: bool,
    lifecycle: str | None,
    curated: bool = False,
    is_root: bool | None = None,
    has_declared_parent: bool = False,
    released_at: datetime | None = None,
    now: datetime,
    downloads: int | None = None,
    likes: int | None = None,
    children_count: int = 0,
    has_params: bool = False,
    has_context: bool = False,
    has_license: bool = False,
) -> Significance:
    significance_class = classify(
        official=official,
        lifecycle=lifecycle,
        curated=curated,
        is_root=is_root,
        has_declared_parent=has_declared_parent,
    )
    factors: list[str] = [f"class {significance_class.value}"]
    score = 0.0

    recency = _recency_factor(released_at, now)
    if recency:
        score += _RECENCY_WEIGHT * recency
        factors.append(f"recency {recency:.1f} (+{_RECENCY_WEIGHT * recency:.2f})")

    download_signal = _log_scale(downloads, 8.0)
    if download_signal:
        score += _DOWNLOADS_WEIGHT * download_signal
        factors.append(
            f"downloads {downloads} (+{_DOWNLOADS_WEIGHT * download_signal:.2f})"
        )

    children_signal = min(children_count / 20.0, 1.0)
    if children_signal:
        score += _CHILDREN_WEIGHT * children_signal
        factors.append(
            f"derivatives {children_count} "
            f"(+{_CHILDREN_WEIGHT * children_signal:.2f})"
        )

    completeness = (
        sum((has_params, has_context, has_license)) / 3.0
    )
    if completeness:
        score += _COMPLETENESS_WEIGHT * completeness
        factors.append(
            f"completeness {completeness:.2f} "
            f"(+{_COMPLETENESS_WEIGHT * completeness:.2f})"
        )

    likes_signal = _log_scale(likes, 5.0)
    if likes_signal:
        score += _LIKES_WEIGHT * likes_signal
        factors.append(f"likes {likes} (+{_LIKES_WEIGHT * likes_signal:.2f})")

    if curated or (lifecycle in _CURATED_LIFECYCLES):
        score += _CURATED_BONUS
        factors.append(f"curated (+{_CURATED_BONUS:.2f})")

    return Significance(
        significance_class=significance_class,
        rank=SIGNIFICANCE_RANK[significance_class],
        score=round(min(score, 1.0), 4),
        factors=factors,
    )


def significance_sort_key(
    significance: Significance,
    release_id: str,
) -> tuple[int, float, str]:
    """Ascending sort: best class first, then highest score, then stable id."""
    return (significance.rank, -significance.score, release_id)
