"""Tests for the separate Try This Week delta report."""

from __future__ import annotations

from radar.models import Category, DecisionCard, Ring
from radar.pipeline.delta import compute_deltas
from radar.reports.try_this_week import render_try_this_week_report


def _card(
    project: str,
    ring: Ring,
    category: Category = Category.CODING_AGENTS,
    what_changed: list[str] | None = None,
    evidence: list[str] | None = None,
) -> DecisionCard:
    return DecisionCard(
        project=project,
        category=category,
        ring=ring,
        summary=f"{project} summary.",
        workflow_fit={"personal_dev": "high"},
        risk_level="low",
        what_changed=what_changed or [],
        evidence=evidence or [],
    )


def test_empty_deltas_render_quiet_week() -> None:
    report = render_try_this_week_report([], "Try This Week")
    assert "# Try This Week" in report
    assert "No changes since the last scan." in report


def test_new_project_appears_under_new_section() -> None:
    current = [_card("Aider", Ring.PILOT, evidence=["https://github.com/Aider-AI/aider"])]
    deltas = compute_deltas(previous=[], current=current)
    report = render_try_this_week_report(deltas, "Try This Week")
    assert "## New on the radar" in report
    assert "Aider" in report
    assert "https://github.com/Aider-AI/aider" in report


def test_promoted_project_appears_under_promoted_section() -> None:
    previous = [_card("Goose", Ring.WATCH)]
    current = [_card("Goose", Ring.PILOT)]
    deltas = compute_deltas(previous=previous, current=current)
    report = render_try_this_week_report(deltas, "Try This Week")
    assert "## Promoted" in report
    assert "Goose" in report
    assert "watch -> pilot" in report


def test_updated_project_lists_new_highlights() -> None:
    previous = [_card("vLLM", Ring.PILOT, what_changed=["Repo snapshot: 100 stars."])]
    current = [
        _card(
            "vLLM",
            Ring.PILOT,
            what_changed=["Repo snapshot: 120 stars.", "release: v0.9.0 adds FP8."],
        )
    ]
    deltas = compute_deltas(previous=previous, current=current)
    report = render_try_this_week_report(deltas, "Try This Week")
    assert "## Updated" in report
    assert "v0.9.0 adds FP8" in report


def test_report_is_deterministic_and_trailing_newline() -> None:
    current = [_card("Aider", Ring.PILOT)]
    deltas = compute_deltas(previous=[], current=current)
    report = render_try_this_week_report(deltas, "Try This Week")
    assert report.endswith("\n")
    assert render_try_this_week_report(deltas, "Try This Week") == report
