"""Momentum: 1-5 score + direction from technique metric history."""

from __future__ import annotations

from datetime import datetime

from radar.research_radar.momentum import MomentumSignal, momentum_signal
from radar.storage.technique_metrics_store import TechniqueMetrics


def _row(count: int | None, source: str | None = "s2", impls: int = 2,
         at: str = "2026-07-01T10:00:00+00:00") -> TechniqueMetrics:
    return TechniqueMetrics(
        technique_id="t", run_id="r", observed_at=datetime.fromisoformat(at),
        citation_count=count, citation_source=source, resolved_impls=impls,
    )


def test_first_scan_is_steady_3():
    signal = momentum_signal("t", [], citation_count=100, citation_source="s2", impl_count=2)

    assert signal == MomentumSignal(technique_id="t", score=3, direction="steady",
                                    citation_growth_pct=None, note=signal.note)


def test_new_implementation_scores_5():
    signal = momentum_signal("t", [_row(100, impls=2)], 100, "s2", impl_count=3)

    assert signal.score == 5
    assert signal.direction == "rising"
    assert "implementation" in signal.note


def test_citation_velocity_above_threshold_scores_4():
    signal = momentum_signal("t", [_row(100)], citation_count=115, citation_source="s2",
                             impl_count=2)

    assert signal.score == 4
    assert signal.direction == "rising"
    assert signal.citation_growth_pct == 15.0


def test_flat_citations_steady_3():
    signal = momentum_signal("t", [_row(100)], 104, "s2", impl_count=2)

    assert signal.score == 3
    assert signal.direction == "steady"


def test_negative_velocity_scores_2():
    signal = momentum_signal("t", [_row(100)], 90, "s2", impl_count=2)

    assert signal.score == 2
    assert signal.direction == "falling"


def test_negative_velocity_and_lost_impl_scores_1():
    signal = momentum_signal("t", [_row(100, impls=3)], 90, "s2", impl_count=2)

    assert signal.score == 1
    assert signal.direction == "falling"


def test_velocity_ignores_rows_from_other_source():
    # Last s2 row was 100; an openalex row in between must not poison the comparison.
    rows = [_row(100, "s2", at="2026-07-01T10:00:00+00:00"),
            _row(34, "openalex", at="2026-07-02T10:00:00+00:00")]

    signal = momentum_signal("t", rows, 115, "s2", impl_count=2)

    assert signal.citation_growth_pct == 15.0
    assert signal.score == 4


def test_no_same_source_history_means_no_velocity():
    signal = momentum_signal("t", [_row(34, "openalex")], 1697, "s2", impl_count=2)

    assert signal.citation_growth_pct is None
    assert signal.score == 3


def test_missing_current_citations_still_uses_impl_delta():
    signal = momentum_signal("t", [_row(100, impls=2)], None, None, impl_count=3)

    assert signal.score == 5


def test_zero_count_same_source_baseline_yields_no_velocity():
    signal = momentum_signal("t", [_row(0)], 50, "s2", impl_count=2)

    assert signal.citation_growth_pct is None
    assert signal.score == 3


def test_new_impl_wins_over_negative_velocity():
    signal = momentum_signal("t", [_row(100, impls=2)], 80, "s2", impl_count=3)

    assert signal.score == 5
    assert signal.direction == "rising"


def test_lost_impl_with_flat_growth_falls_to_2():
    signal = momentum_signal("t", [_row(100, impls=3)], 100, "s2", impl_count=2)

    assert signal.score == 2
    assert signal.direction == "falling"


def test_lost_impl_with_rising_citations_still_falls():
    signal = momentum_signal("t", [_row(100, impls=3)], 120, "s2", impl_count=2)

    assert signal.score == 2
    assert signal.direction == "falling"
