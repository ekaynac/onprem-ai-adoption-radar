"""Tests for the cumulative project-history Markdown report (Phase C)."""

from __future__ import annotations

from datetime import datetime, timezone

from radar.models import Category, Ring
from radar.pipeline.delta import ChangeType
from radar.reports.history import render_history_report
from radar.storage.history_store import ProjectHistoryEvent, ProjectHistorySummary


def _at(day: int) -> datetime:
    return datetime(2026, 6, day, 12, 0, tzinfo=timezone.utc)


def _summary(project: str, ring: Ring, count: int) -> ProjectHistorySummary:
    return ProjectHistorySummary(
        project=project,
        category=Category.MODEL_SERVING,
        current_ring=ring,
        first_seen=_at(10),
        last_change_at=_at(12),
        last_change_type=ChangeType.PROMOTED,
        change_count=count,
    )


def _event(project: str, change: ChangeType, ring: Ring, day: int) -> ProjectHistoryEvent:
    return ProjectHistoryEvent(
        project=project,
        category=Category.MODEL_SERVING,
        change_type=change,
        ring=ring,
        run_id="run-x",
        observed_at=_at(day),
        reasons=["moved up"],
    )


def test_history_report_renders_title_and_projects():
    report = render_history_report(
        summaries=[_summary("Ollama", Ring.PILOT, 2)],
        events_by_project={
            "Ollama": [
                _event("Ollama", ChangeType.NEW, Ring.WATCH, 10),
                _event("Ollama", ChangeType.PROMOTED, Ring.PILOT, 12),
            ]
        },
        title="Adoption History",
    )

    assert report.startswith("# Adoption History")
    assert "Ollama" in report
    assert "2026-06-10" in report  # first seen
    assert "pilot" in report
    assert "promoted" in report


def test_history_report_handles_empty():
    report = render_history_report(summaries=[], events_by_project={}, title="History")

    assert "# History" in report
    assert "No history recorded yet." in report
