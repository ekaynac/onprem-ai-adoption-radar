"""Pins on the shared stylesheet (_base_styles.html) — readability pass."""

from __future__ import annotations

import re
from pathlib import Path


STYLES = Path("src/radar/web/templates/_base_styles.html").read_text(encoding="utf-8")


def test_hero_uses_dedicated_dark_brand_shade():
    assert "--hero-bg: #005F85" in STYLES
    assert re.search(r"\.hero \{[^}]*background: var\(--hero-bg\)", STYLES)


def test_watch_avoid_tokens_with_dark_overrides():
    assert STYLES.count("--watch:") == 2 and STYLES.count("--avoid:") == 2  # :root + dark
    assert "--watch: #D9A519" in STYLES and "--avoid: #EC6A60" in STYLES    # dark values


def test_no_hardcoded_status_hex_outside_token_definitions():
    # every former #8C6200/#B93025 usage now goes through var(--watch)/var(--avoid)
    for hexcode in ("#8C6200", "#B93025"):
        uses = [ln for ln in STYLES.splitlines() if hexcode in ln and "--watch" not in ln
                and "--avoid" not in ln]
        assert uses == [], f"{hexcode} still hardcoded: {uses}"


def test_new_rules_present():
    assert re.search(r"(^|\s)h3 \{", STYLES)                      # heading tier (#10)
    assert "main p { max-width: 70ch" in STYLES                    # measure (#13)
    assert ".table-wrap { overflow-x: auto" in STYLES              # responsive (#3)
    assert re.search(r"td\.num, th\.num \{[^}]*tabular-nums", STYLES)  # numeric (#9)
    assert ".warning { color: var(--avoid)" in STYLES              # (#14)
    assert "font-size: 0.75rem" in STYLES and "font-size: 0.72rem" not in STYLES  # th (#16)
    assert "td.dim { font-weight: 600" in STYLES                   # compare row-label emphasis
    assert ".dim { color: var(--muted)" not in STYLES               # no longer dimmed


def test_error_class_present_next_to_warning():
    # /compare's invalid-input feedback (`<p class="error">`) needs styling —
    # the bespoke stylesheet that defined it was deleted in the design-system
    # conversion, leaving it unstyled until restored here.
    assert ".error { color: var(--avoid); font-weight: 600; }" in STYLES


def test_filter_bar_label_and_button_rules_present():
    # restores the bespoke filter form ergonomics (stacked labels + a styled
    # submit button) lost in the design-system conversion.
    assert re.search(r"\.filter-bar label \{[^}]*flex-direction: column", STYLES)
    assert re.search(r"\.filter-bar button \{[^}]*cursor: pointer", STYLES)


def test_signal_badge_classes_present():
    for cls in (".trend-up", ".trend-down", ".trend-flat",
                ".risk-low", ".risk-medium", ".risk-high",
                ".fit-yes", ".fit-tight", ".fit-no"):
        assert cls in STYLES, f"missing {cls}"


def test_tagline_and_generated_contrast_raised():
    assert "rgba(255,255,255,0.82)" not in STYLES and "rgba(255,255,255,0.7)" not in STYLES


def test_no_headings_inside_table_wrap():
    for tpl in Path("src/radar/web/templates").glob("*.html"):
        text = tpl.read_text(encoding="utf-8")
        # between a wrap-open and its <table>, no heading/paragraph may appear
        for m in re.finditer(r'<div class="table-wrap">(.*?)<table', text, re.S):
            inner = m.group(1)
            assert not re.search(r"<h[1-4]|<p[ >]", inner), f"{tpl.name}: heading/paragraph inside table-wrap"
