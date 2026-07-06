"""Deterministic Mega-branded SVG social cards."""

from __future__ import annotations

from datetime import UTC, datetime
from xml.dom.minidom import parseString

from radar.discovery.trending_entities import Lane, TrendingEntry
from radar.reports.digest import DigestChange, WeeklyDigest
from radar.web.cards import CARD_SIZES, PROCESS_BLUE, render_card, write_cards


def test_render_card_wellformed_branded_and_sized():
    svg = render_card("Trending this week", ["vllm/vllm  +240★/day", "a&b/x  +9★/day"],
                      "portrait")
    parseString(svg)  # well-formed XML
    assert 'width="1080"' in svg and 'height="1350"' in svg
    assert PROCESS_BLUE in svg
    assert "MEGA" in svg
    assert "vllm/vllm" in svg
    assert "a&amp;b/x" in svg      # escaped, not raw '&'


def test_render_card_both_sizes():
    for size, (w, h) in CARD_SIZES.items():
        svg = render_card("H", ["r"], size)
        assert f'width="{w}"' in svg and f'height="{h}"' in svg


def test_render_card_clamps_rows_to_fit_small_size():
    rows = [f"row{i}" for i in range(6)]
    svg = render_card("H", rows, "og")   # 630px tall → fewer than 6 rows fit

    # rows beyond what fits are dropped, not overlapped onto the tagline/edge
    assert svg.count('font-size="40"') < 6
    assert "row0" in svg               # top rows still present


def _digest():
    entry = TrendingEntry(repo="acme/rocket", lane=Lane.ONPREM, stars=1500,
                          velocity_per_day=42.0, is_new=True, first_seen="2026-07-01",
                          description="d", topics=["llm"])
    change = DigestChange(kind="tool", name="Cline", change_type="promoted", ring="adopt",
                          previous_ring="trial", observed_at=datetime(2026, 7, 7, tzinfo=UTC))
    return WeeklyDigest(label="2026-W28",
                        week_start=datetime(2026, 7, 6, tzinfo=UTC),
                        week_end=datetime(2026, 7, 13, tzinfo=UTC),
                        generated_at=datetime(2026, 7, 8, tzinfo=UTC),
                        trending_onprem=[entry], trending_broader=[],
                        auto_added=[], changes=[change])


def test_write_cards_emits_both_sizes(tmp_path):
    paths = write_cards(_digest(), tmp_path)

    names = {p.name for p in paths}
    assert "trending_portrait.svg" in names and "trending_og.svg" in names
    assert "movers_portrait.svg" in names           # changes present → movers card
    assert (tmp_path / "trending_portrait.svg").read_text(encoding="utf-8")


def test_write_cards_skips_movers_when_no_changes(tmp_path):
    d = _digest().model_copy(update={"changes": []})
    names = {p.name for p in write_cards(d, tmp_path)}
    assert not any("movers" in n for n in names)
