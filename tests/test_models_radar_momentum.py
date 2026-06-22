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


def test_download_growth_marks_rising():
    rows = [_row(18, 1000), _row(22, 1100)]  # +10%
    m = compute_model_momentum("m", rows, [])
    assert m.direction == "rising" and m.downloads_growth_pct == 10.0


def test_download_drop_marks_falling():
    rows = [_row(18, 1000), _row(22, 900)]  # -10%
    assert compute_model_momentum("m", rows, []).direction == "falling"


def test_promotion_event_marks_rising():
    ev = ModelHistoryEvent(model_id="m", family="F", change_type=ChangeType.PROMOTED,
                           ring=Ring.ADOPT, run_id="r2", observed_at=NOW)
    assert compute_model_momentum("m", [_row(22, 100)], [ev]).direction == "rising"


def test_flat_is_steady():
    rows = [_row(18, 1000), _row(22, 1000)]
    assert compute_model_momentum("m", rows, []).direction == "steady"
