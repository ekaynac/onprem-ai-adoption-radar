from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.models import Ring
from radar.models_radar.entities import HardwareTier, ModelEntry, Openness, Platform, QuantVariant
from radar.web.picker_context import picker_context
from radar.web.static_site import render_static_site


def test_picker_context_has_presets_and_fractions():
    ctx = picker_context()
    assert ctx["usable_fraction"]["gpu"] == 0.85
    ids = {d["id"] for d in ctx["device_presets"]}
    assert "rtx-4090-24gb" in ids
    a = next(d for d in ctx["device_presets"] if d["id"] == "rtx-4090-24gb")
    assert a["usable_gb"] == 20.4 and a["kind"] == "gpu"


def test_picker_context_tight_fraction_matches_device_fit():
    # The picker's row-coloring threshold is the single source of truth in device_fit.
    from radar.models_radar.device_fit import TIGHT_FRACTION

    assert picker_context()["tight_fraction"] == TIGHT_FRACTION


def test_static_models_page_injects_tight_fraction(tmp_path: Path):
    m = ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3", ring=Ring.ADOPT,
                   hardware_tier=HardwareTier.LAPTOP, openness=Openness.OPEN_PERMISSIVE,
                   quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5, est_memory_gb_4k=8.4,
                                        platform=Platform.GENERIC, source="x")])
    render_static_site([], tmp_path / "_site", datetime(2026, 6, 22, tzinfo=UTC), model_entries=[m])
    html = (tmp_path / "_site" / "models.html").read_text(encoding="utf-8")
    assert "RADAR_TIGHT_FRACTION" in html


def test_static_models_page_has_picker_and_row_data(tmp_path: Path):
    m = ModelEntry(id="qwen3-8b", name="Qwen3 8B", family="Qwen3", ring=Ring.ADOPT,
                   hardware_tier=HardwareTier.LAPTOP, openness=Openness.OPEN_PERMISSIVE,
                   quants=[QuantVariant(format="Q4_K_M", bits_per_weight=4.5, est_memory_gb_4k=8.4,
                                        platform=Platform.GENERIC, source="x"),
                           QuantVariant(format="Q8_0", bits_per_weight=8.0, est_memory_gb_4k=12.0,
                                        platform=Platform.GENERIC, source="x")])
    render_static_site([], tmp_path / "_site", datetime(2026, 6, 22, tzinfo=UTC), model_entries=[m])
    html = (tmp_path / "_site" / "models.html").read_text(encoding="utf-8")
    assert 'id="device-select"' in html
    assert 'data-min-memory-gb="8.4"' in html   # min across quants, not first
    assert "RADAR_USABLE_FRACTION" in html and "rtx-4090-24gb" in html
