"""Tests for model mover lines report generation."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.models import Ring
from radar.models_radar.entities import HardwareTier, ModelEntry, Openness
from radar.models_radar.history import ModelHistoryEvent
from radar.models_radar.momentum import ModelMomentum
from radar.models_radar.reports import (
    build_model_mover_lines,
    model_events_to_feed_atom,
    model_events_to_feed_json,
    render_model_report,
)
from radar.storage.history_store import ChangeType


NOW = datetime(2026, 6, 22, tzinfo=UTC)


def _ev(mid, ct, ring, prev=None):
    return ModelHistoryEvent(model_id=mid, family="F", change_type=ct, ring=ring,
                             previous_ring=prev, run_id="r", observed_at=NOW)


def test_ring_changes_first_then_trending():
    events = [_ev("a", ChangeType.PROMOTED, Ring.ADOPT, Ring.PILOT),
              _ev("b", ChangeType.NEW, Ring.PILOT)]
    moms = [ModelMomentum(model_id="c", direction="rising", downloads_growth_pct=12.0,
                          note="Downloads +12.0%"),
            ModelMomentum(model_id="a", direction="rising", downloads_growth_pct=5.0)]
    lines = build_model_mover_lines(events, moms)
    assert any("a:" in line and "promoted" in line for line in lines)
    assert any("b:" in line and "new" in line for line in lines)
    # c trends; a already shown as a ring move → not repeated in trending
    assert any("c:" in line and "rising" in line for line in lines)
    assert sum(1 for line in lines if line.startswith("a:")) == 1


def test_empty_inputs_yield_no_lines():
    assert build_model_mover_lines([], []) == []


def test_render_model_report_has_sections():
    e = ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3", ring=Ring.ADOPT,
                   hardware_tier=HardwareTier.LAPTOP, openness=Openness.OPEN_PERMISSIVE)
    md = render_model_report([e], ["qwen3-8b: rising"], "Model Radar")
    assert "# Model Radar" in md and "## Movers" in md and "qwen3-8b" in md
    assert "laptop" in md


def test_model_feeds_build_from_events():
    ev = _ev("qwen3-8b", ChangeType.NEW, Ring.ADOPT)
    j = model_events_to_feed_json([ev], "Model Radar")
    assert j["items"] and "qwen3-8b" in j["items"][0]["title"]
    x = model_events_to_feed_atom([ev], "Model Radar", "https://example/changes-models.xml")
    assert "<feed" in x and "qwen3-8b" in x
