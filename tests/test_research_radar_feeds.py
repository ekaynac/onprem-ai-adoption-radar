"""Technique ring-change feeds (Atom + JSON Feed), mirror of the model feeds."""

from __future__ import annotations

from datetime import datetime

from radar.models import Ring
from radar.research_radar.entities import TechniqueDomain
from radar.research_radar.history import TechniqueHistoryEvent
from radar.research_radar.reports import (
    technique_events_to_feed_atom,
    technique_events_to_feed_json,
)
from radar.storage.history_store import ChangeType


def _event(technique_id: str, ring: Ring, at: str,
           previous: Ring | None = None) -> TechniqueHistoryEvent:
    return TechniqueHistoryEvent(
        technique_id=technique_id, domain=TechniqueDomain.INFERENCE,
        change_type=ChangeType.PROMOTED if previous else ChangeType.NEW,
        ring=ring, previous_ring=previous, run_id="run-1",
        observed_at=datetime.fromisoformat(at),
        reasons=[f"promoted to {ring.value}" if previous else f"new ({ring.value})"],
    )


OLD = _event("lora", Ring.ADOPT, "2026-07-01T10:00:00+00:00")
NEW = _event("medusa-decoding", Ring.PILOT, "2026-07-03T10:00:00+00:00", previous=Ring.WATCH)


def test_json_feed_items_newest_first_with_urn_and_tags():
    feed = technique_events_to_feed_json([OLD, NEW], site_title="Radar")

    assert feed["version"] == "https://jsonfeed.org/version/1.1"
    assert feed["title"] == "Radar — Research"
    assert [i["id"] for i in feed["items"]] == [
        "urn:radar-technique:medusa-decoding:run-1",
        "urn:radar-technique:lora:run-1",
    ]
    assert feed["items"][0]["title"] == "medusa-decoding: watch → pilot (promoted)"
    assert feed["items"][0]["tags"] == ["inference", "pilot"]


def test_atom_feed_escapes_and_carries_self_url():
    feed = technique_events_to_feed_atom([OLD], site_title="R<adar",
                                         self_url="https://x.test/changes-research.xml")

    assert '<link rel="self" href="https://x.test/changes-research.xml"/>' in feed
    assert "R&lt;adar — Research" in feed
    assert "urn:radar-technique:lora:run-1" in feed


def test_atom_feed_empty_events_still_valid():
    feed = technique_events_to_feed_atom([], site_title="Radar", self_url="changes-research.xml")

    assert feed.startswith('<?xml version="1.0"')
    assert "<updated>" in feed
