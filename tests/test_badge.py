"""Shields-style ring/fit badges (deterministic, self-contained SVG)."""

from __future__ import annotations

from xml.dom.minidom import parseString

from radar.web.badge import (
    RING_BADGE_COLORS,
    badge_markdown,
    fit_badge_svg,
    ring_badge_svg,
)


def _rel_luminance(hex_color: str) -> float:
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def test_white_text_contrast_is_aa_on_every_ring_color():
    for ring, color in RING_BADGE_COLORS.items():
        contrast = (1.0 + 0.05) / (_rel_luminance(color) + 0.05)
        assert contrast >= 4.5, f"{ring}: {color} fails AA ({contrast:.2f})"


def test_ring_badge_shape_and_escaping():
    svg = ring_badge_svg("adopt")
    parseString(svg)
    assert "on-prem radar" in svg and "ADOPT" in svg
    assert RING_BADGE_COLORS["adopt"] in svg
    assert 'height="20"' in svg
    assert svg == ring_badge_svg("adopt")  # deterministic


def test_fit_badge_with_and_without_quant():
    svg = fit_badge_svg("workstation", "Q5_K_M")
    parseString(svg)
    assert "runs on" in svg and "workstation (Q5_K_M)" in svg
    assert "workstation (" not in fit_badge_svg("workstation", None)


def test_badge_markdown():
    md = badge_markdown("https://x/badges/vllm.svg", "https://x/project_vllm.html",
                        "On-Prem Radar: ADOPT")
    assert md == "[![On-Prem Radar: ADOPT](https://x/badges/vllm.svg)](https://x/project_vllm.html)"
