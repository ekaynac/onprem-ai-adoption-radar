"""Tests for the subscribable change feeds (Atom + JSON + RSS)."""

from __future__ import annotations

from datetime import UTC, datetime
from xml.etree import ElementTree

from radar.models import Category, Ring
from radar.pipeline.delta import ChangeType
from radar.reports.feeds import render_changes_atom, render_changes_json, render_changes_rss
from radar.storage.history_store import ProjectHistoryEvent


def _event(project: str, day: int, change: ChangeType, ring: Ring) -> ProjectHistoryEvent:
    return ProjectHistoryEvent(
        project=project,
        category=Category.MODEL_SERVING,
        change_type=change,
        ring=ring,
        previous_ring=Ring.PILOT,
        run_id=f"run-{day}",
        observed_at=datetime(2026, 6, day, tzinfo=UTC),
        reasons=["moved"],
    )


def test_atom_feed_is_valid_xml_with_entries():
    events = [
        _event("vLLM", 12, ChangeType.PROMOTED, Ring.ADOPT),
        _event("Aider", 11, ChangeType.DEMOTED, Ring.WATCH),
    ]

    xml = render_changes_atom(events, site_title="Radar", self_url="https://x/changes.xml")

    root = ElementTree.fromstring(xml)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entries = root.findall("a:entry", ns)
    assert len(entries) == 2
    titles = [e.find("a:title", ns).text for e in entries]
    assert any("vLLM" in t and "adopt" in t for t in titles)


def test_atom_feed_newest_first():
    events = [
        _event("Old", 10, ChangeType.PROMOTED, Ring.ADOPT),
        _event("New", 12, ChangeType.PROMOTED, Ring.ADOPT),
    ]

    xml = render_changes_atom(events, site_title="Radar", self_url="https://x/changes.xml")

    assert xml.index("New") < xml.index("Old")


def test_json_feed_structure():
    events = [_event("vLLM", 12, ChangeType.PROMOTED, Ring.ADOPT)]

    feed = render_changes_json(events, site_title="Radar")

    assert feed["version"].startswith("https://jsonfeed.org")
    assert feed["title"] == "Radar"
    item = feed["items"][0]
    assert item["id"]
    assert "vLLM" in item["title"]
    assert item["date_published"].startswith("2026-06-12")


def test_feeds_handle_empty_history():
    assert render_changes_json([], site_title="Radar")["items"] == []
    root = ElementTree.fromstring(
        render_changes_atom([], site_title="Radar", self_url="https://x/changes.xml")
    )
    assert root.findall("{http://www.w3.org/2005/Atom}entry") == []
    rss_root = ElementTree.fromstring(
        render_changes_rss([], site_title="Radar", self_url="https://x/changes.rss")
    )
    assert rss_root.findall("./channel/item") == []


def test_rss_feed_is_valid_rss2_with_items():
    events = [
        _event("vLLM", 12, ChangeType.PROMOTED, Ring.ADOPT),
        _event("Aider", 11, ChangeType.DEMOTED, Ring.WATCH),
    ]

    xml = render_changes_rss(events, site_title="Radar", self_url="https://x/changes.rss")

    root = ElementTree.fromstring(xml)
    assert root.tag == "rss"
    assert root.attrib["version"] == "2.0"
    items = root.findall("./channel/item")
    assert len(items) == 2
    titles = [i.find("title").text for i in items]
    assert any("vLLM" in t and "adopt" in t for t in titles)


def test_rss_feed_newest_first():
    events = [
        _event("Old", 10, ChangeType.PROMOTED, Ring.ADOPT),
        _event("New", 12, ChangeType.PROMOTED, Ring.ADOPT),
    ]

    xml = render_changes_rss(events, site_title="Radar", self_url="https://x/changes.rss")

    assert xml.index("New") < xml.index("Old")


def test_rss_pubdate_is_rfc822():
    events = [_event("vLLM", 12, ChangeType.PROMOTED, Ring.ADOPT)]

    xml = render_changes_rss(events, site_title="Radar", self_url="https://x/changes.rss")

    item = ElementTree.fromstring(xml).find("./channel/item")
    # RFC-822 dates lead with the abbreviated weekday, not an ISO year.
    assert item.find("pubDate").text.startswith("Fri, 12 Jun 2026")
    guid = item.find("guid")
    assert guid.attrib["isPermaLink"] == "false"
    assert guid.text


def test_rss_escapes_special_characters():
    events = [_event("A & B <test>", 12, ChangeType.PROMOTED, Ring.ADOPT)]

    xml = render_changes_rss(events, site_title="R & D", self_url="https://x/c.rss")

    # Must remain parseable (entities escaped, not raw).
    ElementTree.fromstring(xml)


def test_atom_escapes_special_characters():
    events = [_event("A & B <test>", 12, ChangeType.PROMOTED, Ring.ADOPT)]

    xml = render_changes_atom(events, site_title="R", self_url="https://x/c.xml")

    # Must remain parseable (entities escaped, not raw).
    ElementTree.fromstring(xml)


def test_static_export_writes_change_feeds(tmp_path):
    from radar.models import DecisionCard
    from radar.storage.history_store import ProjectHistorySummary
    from radar.web.static_site import render_static_site

    card = DecisionCard(
        project="vLLM", category=Category.MODEL_SERVING, ring=Ring.ADOPT,
        summary="fast", workflow_fit={}, risk_level="low",
    )
    summary = ProjectHistorySummary(
        project="vLLM", category=Category.MODEL_SERVING, current_ring=Ring.ADOPT,
        first_seen=datetime(2026, 6, 10, tzinfo=UTC),
        last_change_at=datetime(2026, 6, 12, tzinfo=UTC),
        last_change_type=ChangeType.PROMOTED, change_count=2,
    )
    timelines = [
        {"summary": summary, "events": [_event("vLLM", 12, ChangeType.PROMOTED, Ring.ADOPT)]}
    ]

    render_static_site(
        [card], tmp_path / "_site", datetime(2026, 6, 13, tzinfo=UTC), timelines=timelines
    )

    assert (tmp_path / "_site" / "changes.xml").exists()
    feed_json = (tmp_path / "_site" / "changes.json").read_text(encoding="utf-8")
    assert "vLLM" in feed_json
    feed_rss = (tmp_path / "_site" / "changes.rss").read_text(encoding="utf-8")
    assert "vLLM" in feed_rss
    assert ElementTree.fromstring(feed_rss).attrib["version"] == "2.0"


def test_static_export_base_url_makes_feed_urls_absolute(tmp_path):
    from radar.models import DecisionCard
    from radar.web.static_site import render_static_site

    card = DecisionCard(
        project="vLLM", category=Category.MODEL_SERVING, ring=Ring.ADOPT,
        summary="fast", workflow_fit={}, risk_level="low",
    )

    render_static_site(
        [card],
        tmp_path / "_site",
        datetime(2026, 6, 13, tzinfo=UTC),
        self_base_url="https://example.test/radar/",  # trailing slash must be normalized
    )

    # Both feeds carry an absolute self/link URL (not the relative filename).
    rss = (tmp_path / "_site" / "changes.rss").read_text(encoding="utf-8")
    atom = (tmp_path / "_site" / "changes.xml").read_text(encoding="utf-8")
    assert "https://example.test/radar/changes.rss" in rss
    assert "changes.rss/" not in rss  # no double slash from the trailing-slash base
    assert "https://example.test/radar/changes.xml" in atom
