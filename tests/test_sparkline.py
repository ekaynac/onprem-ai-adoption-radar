"""Deterministic inline-SVG sparklines (no JS, no external assets)."""

from __future__ import annotations

from xml.dom.minidom import parseString

from radar.web.sparkline import sparkline_svg


def test_renders_wellformed_svg_with_a11y():
    svg = sparkline_svg([1, 5, 3, 8], label="stars, last 4 scans")
    parseString(svg)
    assert 'viewBox="0 0 120 28"' in svg
    assert 'role="img"' in svg
    assert "stars, last 4 scans" in svg
    assert "<polyline" in svg and "<circle" in svg
    assert "currentColor" in svg


def test_below_three_points_renders_nothing():
    assert sparkline_svg([], label="x") == ""
    assert sparkline_svg([1.0], label="x") == ""
    assert sparkline_svg([1.0, 2.0], label="x") == ""


def test_flat_series_has_no_nan_and_midline():
    svg = sparkline_svg([7, 7, 7], label="flat")
    parseString(svg)
    assert "nan" not in svg.lower()
    assert "14.0" in svg or "14," in svg or " 14" in svg


def test_label_is_escaped():
    svg = sparkline_svg([1, 2, 3], label="a<b&c")
    assert "a&lt;b&amp;c" in svg


def test_label_with_quote_stays_wellformed():
    svg = sparkline_svg([1, 2, 3], label='say "hi" & bye')
    parseString(svg)
    assert "&quot;" in svg
    assert "&amp;" in svg


def test_deterministic():
    a = sparkline_svg([1, 2, 3, 10], label="d")
    assert a == sparkline_svg([1, 2, 3, 10], label="d")
