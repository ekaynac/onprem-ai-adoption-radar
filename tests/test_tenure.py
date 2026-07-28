"""Tenure credential lines computed from ring timelines."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.models import Category, Ring
from radar.pipeline.delta import ChangeType
from radar.storage.history_store import ProjectHistoryEvent
from radar.web.tenure import model_tenure, project_tenure


NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def _ev(day: int, ring: Ring, change: ChangeType = ChangeType.UPDATED,
        run: str = "", corrects: str | None = None) -> ProjectHistoryEvent:
    return ProjectHistoryEvent(
        project="vLLM", category=Category.MODEL_SERVING, change_type=change,
        ring=ring, previous_ring=None, run_id=run or f"run-{day}",
        observed_at=datetime(2026, 7, day, tzinfo=UTC), reasons=[],
        corrects_run_id=corrects,
    )


def test_tenure_line_text_and_streak():
    events = [
        _ev(1, Ring.WATCH, ChangeType.NEW),
        _ev(10, Ring.PILOT, ChangeType.PROMOTED),
        _ev(20, Ring.ADOPT, ChangeType.PROMOTED),
        _ev(25, Ring.ADOPT, ChangeType.UPDATED),
    ]
    line = project_tenure(events, NOW)
    assert line is not None
    assert line.days_on_radar == 27
    assert line.ring == "adopt"
    assert line.ring_since == "2026-07-20"   # streak start, not last event
    # watch -> pilot -> adopt = 2 transitions; the day-25 `updated` at the
    # same ring is NOT a ring change.
    assert line.change_count == 2
    assert line.text == "On radar 27 days · ADOPT since 2026-07-20 · 2 ring changes"


def test_single_event_is_singular_free():
    line = project_tenure([_ev(28, Ring.WATCH, ChangeType.NEW)], NOW)
    assert line is not None
    assert line.change_count == 0
    assert "0 ring changes" in line.text
    assert line.text.startswith("On radar since today")


def test_corrected_events_do_not_inflate_tenure():
    artifact = _ev(15, Ring.ADOPT, ChangeType.PROMOTED, run="run-outage")
    marker = _ev(16, Ring.WATCH, ChangeType.CORRECTED, run="repair:run-outage",
                 corrects="run-outage")
    clean = [_ev(1, Ring.WATCH, ChangeType.NEW), _ev(20, Ring.WATCH, ChangeType.UPDATED)]
    with_noise = [clean[0], artifact, marker, clean[1]]
    assert project_tenure(with_noise, NOW) == project_tenure(clean, NOW)


def test_fully_corrected_project_has_no_tenure():
    events = [
        _ev(15, Ring.ADOPT, ChangeType.PROMOTED, run="run-x"),
        _ev(16, Ring.WATCH, ChangeType.CORRECTED, run="repair:run-x", corrects="run-x"),
    ]
    assert project_tenure(events, NOW) is None


def test_model_tenure_same_shape():
    from radar.models_radar.history import ModelHistoryEvent

    events = [
        ModelHistoryEvent(model_id="m", family="F", change_type=ChangeType.NEW,
                          ring=Ring.PILOT, previous_ring=None, run_id="r1",
                          observed_at=datetime(2026, 7, 1, tzinfo=UTC), reasons=[]),
        ModelHistoryEvent(model_id="m", family="F", change_type=ChangeType.PROMOTED,
                          ring=Ring.ADOPT, previous_ring=Ring.PILOT, run_id="r2",
                          observed_at=datetime(2026, 7, 10, tzinfo=UTC), reasons=[]),
    ]
    line = model_tenure(events, NOW)
    assert line is not None and line.ring == "adopt" and line.change_count == 1
    assert "1 ring change" in line.text and "changes" not in line.text
