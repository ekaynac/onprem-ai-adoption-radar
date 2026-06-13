"""Tests for the scoring-calibration diagnostic report."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.analysis.calibration import (
    build_calibration_report,
    render_calibration_markdown,
)
from radar.models import Category, Ring, ScoreBreakdown, ScoredSignal, Signal
from radar.pipeline.delta import ChangeType
from radar.storage.history_store import ProjectHistoryEvent


def _scored(project: str, avg_dims: int, security: int, reasons: list[str]) -> ScoredSignal:
    return ScoredSignal(
        signal=Signal(
            id=project, source_id="s", project=project,
            category=Category.MODEL_SERVING, title=project,
            url="https://example.com", signal_type="github_repo_snapshot",
            published_at=datetime(2026, 6, 12, tzinfo=UTC),
        ),
        scores=ScoreBreakdown(
            workflow_impact=avg_dims, laptop_runnability=avg_dims,
            open_source_maturity=avg_dims, on_prem_relevance=avg_dims,
            security_posture=security, demo_value=avg_dims, setup_friction=avg_dims,
        ),
        recommended_ring=Ring.PILOT,
        reason_codes=reasons,
    )


def _event(project: str, day: int, change: ChangeType) -> ProjectHistoryEvent:
    return ProjectHistoryEvent(
        project=project, category=Category.MODEL_SERVING, change_type=change,
        ring=Ring.PILOT, run_id=f"run-{day}",
        observed_at=datetime(2026, 6, day, tzinfo=UTC),
    )


def test_report_computes_score_distribution_and_ring_counts():
    scored = [
        _scored("A", 5, 5, ["recent_security_advisories"]),
        _scored("B", 4, 4, []),
        _scored("C", 3, 3, ["active_development"]),
        _scored("D", 2, 2, ["needs_sandbox_review"]),
    ]
    ring_by_project = {"A": Ring.ADOPT, "B": Ring.PILOT, "C": Ring.WATCH, "D": Ring.AVOID}

    report = build_calibration_report(scored, ring_by_project, history_events=[])

    assert report.score_stats.count == 4
    assert report.score_stats.minimum <= report.score_stats.median <= report.score_stats.maximum
    assert report.ring_counts["adopt"] == 1
    assert report.ring_counts["avoid"] == 1


def test_report_tallies_evidence_impact():
    scored = [
        _scored("A", 5, 5, ["recent_security_advisories", "active_development"]),
        _scored("B", 4, 4, ["active_development"]),
        _scored("C", 3, 3, ["license_changed"]),
    ]
    rings = {"A": Ring.WATCH, "B": Ring.PILOT, "C": Ring.WATCH}

    report = build_calibration_report(scored, rings, history_events=[])

    assert report.evidence_impact["active_development"] == 2
    assert report.evidence_impact["recent_security_advisories"] == 1
    assert report.evidence_impact["license_changed"] == 1


def test_report_measures_ring_churn_from_history():
    history = [
        _event("A", 1, ChangeType.NEW),
        _event("A", 2, ChangeType.PROMOTED),  # a flip
        _event("A", 3, ChangeType.DEMOTED),   # another flip
        _event("B", 1, ChangeType.NEW),       # no flips
    ]
    scored = [_scored("A", 4, 4, []), _scored("B", 4, 4, [])]
    rings = {"A": Ring.PILOT, "B": Ring.PILOT}

    report = build_calibration_report(scored, rings, history_events=history)

    # Ring-moving events (promoted/demoted) across all projects.
    assert report.churn.total_ring_moves == 2
    assert report.churn.projects_with_moves == 1


def test_report_flags_discrimination_when_one_ring_dominates():
    scored = [_scored(p, 4, 4, []) for p in ("A", "B", "C", "D", "E")]
    rings = dict.fromkeys(("A", "B", "C", "D", "E"), Ring.PILOT)  # all one ring

    report = build_calibration_report(scored, rings, history_events=[])

    assert report.dominant_ring_fraction == 1.0
    assert report.discriminates is False


def test_render_markdown_includes_sections():
    scored = [_scored("A", 5, 5, ["active_development"]), _scored("B", 2, 2, [])]
    rings = {"A": Ring.ADOPT, "B": Ring.WATCH}

    md = render_calibration_markdown(
        build_calibration_report(scored, rings, history_events=[])
    )

    assert "# Scoring Calibration" in md
    assert "Score distribution" in md
    assert "Ring distribution" in md
    assert "Evidence impact" in md


def test_empty_input_is_safe():
    report = build_calibration_report([], {}, history_events=[])

    assert report.score_stats.count == 0
    assert report.ring_counts == {}
    md = render_calibration_markdown(report)
    assert "no scored signals" in md.lower()
