"""Tests for the scoring-backtest report builder and renderer."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.analysis.backtest import (
    RunBacktest,
    build_backtest_report,
    render_backtest_markdown,
)
from radar.models import Category, DecisionCard, Ring


def _card(project: str, ring: Ring) -> DecisionCard:
    return DecisionCard(
        project=project, category=Category.MODEL_SERVING, ring=ring,
        summary="s", workflow_fit={}, risk_level="low",
    )


def test_build_report_detects_ring_moves():
    baseline = [_card("vLLM", Ring.PILOT), _card("Aider", Ring.PILOT)]
    candidate = [_card("vLLM", Ring.ADOPT), _card("Aider", Ring.PILOT)]
    run = RunBacktest.from_card_sets(
        run_id="run-1",
        created_at=datetime(2026, 6, 10, tzinfo=UTC),
        baseline=baseline,
        candidate=candidate,
    )

    report = build_backtest_report(mode="profile:security-first", runs=[run])

    assert report.total_moves == 1
    assert report.runs_analyzed == 1
    moved = report.runs[0].moved
    assert len(moved) == 1
    assert moved[0].project == "vLLM"
    assert moved[0].baseline_ring == Ring.PILOT
    assert moved[0].candidate_ring == Ring.ADOPT


def test_no_moves_when_card_sets_identical():
    cards = [_card("vLLM", Ring.ADOPT)]
    run = RunBacktest.from_card_sets(
        run_id="run-1",
        created_at=datetime(2026, 6, 10, tzinfo=UTC),
        baseline=cards,
        candidate=[_card("vLLM", Ring.ADOPT)],
    )

    report = build_backtest_report(mode="config-drift", runs=[run])

    assert report.total_moves == 0
    assert report.runs[0].moved == []


def test_ring_counts_captured_per_side():
    run = RunBacktest.from_card_sets(
        run_id="run-1",
        created_at=datetime(2026, 6, 10, tzinfo=UTC),
        baseline=[_card("A", Ring.PILOT), _card("B", Ring.WATCH)],
        candidate=[_card("A", Ring.ADOPT), _card("B", Ring.WATCH)],
    )

    assert run.baseline_ring_counts["pilot"] == 1
    assert run.candidate_ring_counts["adopt"] == 1


def test_render_markdown_summarizes_moves():
    run = RunBacktest.from_card_sets(
        run_id="run-1",
        created_at=datetime(2026, 6, 10, tzinfo=UTC),
        baseline=[_card("vLLM", Ring.PILOT)],
        candidate=[_card("vLLM", Ring.ADOPT)],
    )
    md = render_backtest_markdown(
        build_backtest_report(mode="profile:security-first", runs=[run])
    )

    assert "# Scoring Backtest" in md
    assert "security-first" in md
    assert "vLLM" in md
    assert "pilot" in md and "adopt" in md


def test_render_markdown_empty_runs_explains():
    md = render_backtest_markdown(build_backtest_report(mode="config-drift", runs=[]))

    assert "no runs" in md.lower() or "run radar scan" in md.lower()
