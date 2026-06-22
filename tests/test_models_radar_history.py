"""Tests for model ring-change history events."""
from __future__ import annotations

from datetime import UTC, datetime

from radar.models import Ring
from radar.models_radar.entities import ModelEntry
from radar.models_radar.history import (
    append_model_events,
    diff_model_rings,
    load_model_events,
)


NOW = datetime(2026, 6, 22, tzinfo=UTC)


def _e(mid, ring):
    return ModelEntry(id=mid, name=mid, family="F", ring=ring)


def test_new_model_yields_new_event():
    events = diff_model_rings([_e("a", Ring.PILOT)], {}, "r1", NOW)
    assert len(events) == 1 and events[0].change_type.value == "new"
    assert events[0].ring == Ring.PILOT and events[0].previous_ring is None


def test_promotion_and_demotion_detected():
    prev = {"a": Ring.WATCH, "b": Ring.ADOPT}
    events = {e.model_id: e for e in diff_model_rings(
        [_e("a", Ring.ADOPT), _e("b", Ring.PILOT)], prev, "r2", NOW)}
    assert events["a"].change_type.value == "promoted"
    assert events["b"].change_type.value == "demoted"


def test_unchanged_ring_emits_no_event():
    assert diff_model_rings([_e("a", Ring.PILOT)], {"a": Ring.PILOT}, "r2", NOW) == []


def test_log_round_trip(tmp_path):
    path = tmp_path / "model-history.jsonl"
    events = diff_model_rings([_e("a", Ring.PILOT)], {}, "r1", NOW)
    append_model_events(path, events)
    loaded = load_model_events(path)
    assert len(loaded) == 1 and loaded[0].model_id == "a"
