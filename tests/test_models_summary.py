"""Test ModelsSummary summary builder."""

from __future__ import annotations

from radar.models import Ring
from radar.models_radar.entities import HardwareTier, ModelEntry, Openness
from radar.web.models_summary import summarize_models


def _e(mid, ring, tier):
    return ModelEntry(id=mid, name=mid, family="F", ring=ring, hardware_tier=tier,
                      openness=Openness.OPEN_PERMISSIVE)


def test_empty_is_no_models():
    s = summarize_models([])
    assert s.total == 0 and not s.has_models and "no models" in s.one_line.lower()


def test_counts_by_ring_and_tier():
    s = summarize_models([_e("a", Ring.ADOPT, HardwareTier.LAPTOP),
                          _e("b", Ring.ADOPT, HardwareTier.APPLE_HIGH_RAM),
                          _e("c", Ring.PILOT, HardwareTier.LAPTOP)])
    assert s.total == 3 and s.has_models
    assert s.by_ring["adopt"] == 2 and s.by_ring["pilot"] == 1
    assert s.by_tier["laptop"] == 2 and s.by_tier["apple_high_ram"] == 1
