from __future__ import annotations

from datetime import UTC, datetime

from radar.models import Ring
from radar.models_radar.history import ModelHistoryEvent
from radar.models_radar.momentum import compute_model_momentum
from radar.storage.history_store import ChangeType
from radar.storage.model_metrics_store import ModelMetrics


NOW = datetime(2026, 6, 22, tzinfo=UTC)


def _row(day, downloads):
    return ModelMetrics(model_id="m", run_id=f"r{day}",
                        observed_at=datetime(2026, 6, day, tzinfo=UTC), downloads=downloads)


def _event(change, year, month, day):
    return ModelHistoryEvent(model_id="m", family="F", change_type=change,
                             ring=Ring.ADOPT, run_id=f"e{year}{month:02d}{day:02d}",
                             observed_at=datetime(year, month, day, tzinfo=UTC))


def test_download_growth_marks_rising():
    rows = [_row(18, 1000), _row(22, 1100)]  # +10%
    m = compute_model_momentum("m", rows, [], NOW)
    assert m.direction == "rising" and m.downloads_growth_pct == 10.0


def test_download_drop_marks_falling():
    rows = [_row(18, 1000), _row(22, 900)]  # -10%
    assert compute_model_momentum("m", rows, [], NOW).direction == "falling"


def test_promotion_event_marks_rising():
    ev = ModelHistoryEvent(model_id="m", family="F", change_type=ChangeType.PROMOTED,
                           ring=Ring.ADOPT, run_id="r2", observed_at=NOW)
    assert compute_model_momentum("m", [_row(22, 100)], [ev], NOW).direction == "rising"


def test_flat_is_steady():
    rows = [_row(18, 1000), _row(22, 1000)]
    assert compute_model_momentum("m", rows, [], NOW).direction == "steady"


def test_old_demotion_no_longer_forces_falling():
    now = datetime(2026, 7, 8, tzinfo=UTC)
    ev = _event(ChangeType.DEMOTED, 2026, 5, 1)  # ~2 months old
    rows = [_row(1, 100), _row(6, 100)]  # flat downloads
    m = compute_model_momentum("m", rows, [ev], now)
    assert m.direction == "steady"  # stale event ignored


def test_recent_demotion_still_falls():
    now = datetime(2026, 7, 8, tzinfo=UTC)
    ev = _event(ChangeType.DEMOTED, 2026, 7, 5)  # 3 days old
    m = compute_model_momentum("m", [_row(1, 100)], [ev], now)
    assert m.direction == "falling"
