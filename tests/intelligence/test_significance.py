from __future__ import annotations

from datetime import UTC, datetime, timedelta

from radar.intelligence.significance import (
    Significance,
    SignificanceClass,
    classify,
    compute_significance,
    significance_sort_key,
)


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def test_class_ladder_first_match_wins() -> None:
    assert (
        classify(official=True, lifecycle="detected", is_root=True)
        is SignificanceClass.OFFICIAL_ROOT
    )
    assert (
        classify(official=False, lifecycle="detected", is_root=True)
        is SignificanceClass.BASE_RELEASE
    )
    assert (
        classify(official=True, lifecycle="detected", is_root=False)
        is SignificanceClass.OFFICIAL_PUBLISHER
    )
    assert (
        classify(official=False, lifecycle="qualified")
        is SignificanceClass.CURATED
    )
    assert (
        classify(official=False, lifecycle="detected", has_declared_parent=True)
        is SignificanceClass.DECLARED_DERIVATIVE
    )
    assert (
        classify(official=False, lifecycle="verified")
        is SignificanceClass.VERIFIED_DERIVATIVE
    )
    assert (
        classify(official=False, lifecycle="detected")
        is SignificanceClass.PROVISIONAL
    )


def test_unknown_root_status_never_reads_as_base() -> None:
    # is_root=None means "never checked" — it must not upgrade the class.
    assert (
        classify(official=False, lifecycle="verified", is_root=None)
        is SignificanceClass.VERIFIED_DERIVATIVE
    )
    assert (
        classify(official=True, lifecycle="detected", is_root=None)
        is SignificanceClass.OFFICIAL_PUBLISHER
    )


def test_official_root_outranks_fresh_popular_derivative() -> None:
    root = compute_significance(
        official=True,
        lifecycle="verified",
        is_root=True,
        released_at=NOW - timedelta(days=200),
        now=NOW,
        downloads=1000,
        children_count=40,
    )
    clone = compute_significance(
        official=False,
        lifecycle="detected",
        has_declared_parent=True,
        released_at=NOW - timedelta(hours=1),
        now=NOW,
        downloads=5_000_000,
        likes=10_000,
    )
    assert significance_sort_key(root, "release:root") < significance_sort_key(
        clone, "release:clone"
    )


def test_score_is_bounded_deterministic_and_cited() -> None:
    significance = compute_significance(
        official=True,
        lifecycle="recommended",
        is_root=True,
        released_at=NOW - timedelta(days=2),
        now=NOW,
        downloads=5_000_000,
        likes=9_000,
        children_count=189,
        has_params=True,
        has_context=True,
        has_license=True,
    )
    again = compute_significance(
        official=True,
        lifecycle="recommended",
        is_root=True,
        released_at=NOW - timedelta(days=2),
        now=NOW,
        downloads=5_000_000,
        likes=9_000,
        children_count=189,
        has_params=True,
        has_context=True,
        has_license=True,
    )
    assert significance == again
    assert 0.0 < significance.score <= 1.0
    assert significance.factors[0] == "class official_root"
    # Every non-zero contribution names itself.
    assert any(factor.startswith("recency") for factor in significance.factors)
    assert any(factor.startswith("downloads") for factor in significance.factors)
    assert any(factor.startswith("derivatives") for factor in significance.factors)
    assert any(factor.startswith("completeness") for factor in significance.factors)
    assert any(factor.startswith("likes") for factor in significance.factors)
    assert any(factor.startswith("curated") for factor in significance.factors)


def test_missing_signals_contribute_nothing_and_are_not_cited() -> None:
    significance = compute_significance(
        official=False,
        lifecycle="detected",
        now=NOW,
    )
    assert significance.score == 0.0
    assert significance.factors == ["class provisional"]


def test_within_class_score_orders_and_id_breaks_ties() -> None:
    stronger = compute_significance(
        official=False,
        lifecycle="detected",
        has_declared_parent=True,
        now=NOW,
        downloads=100_000,
    )
    weaker = compute_significance(
        official=False,
        lifecycle="detected",
        has_declared_parent=True,
        now=NOW,
        downloads=10,
    )
    assert significance_sort_key(stronger, "release:b") < significance_sort_key(
        weaker, "release:a"
    )
    tie = Significance(
        significance_class=SignificanceClass.PROVISIONAL,
        rank=6,
        score=0.0,
    )
    assert significance_sort_key(tie, "release:a") < significance_sort_key(
        tie, "release:b"
    )
