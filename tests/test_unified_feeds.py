from __future__ import annotations

import json
from datetime import UTC, datetime
from xml.etree import ElementTree

import pytest

from radar.intelligence.contracts import LifecycleState
from radar.intelligence.events import IntelligenceEvent
from radar.models import Category, Ring
from radar.pipeline.delta import ChangeType
from radar.reports.unified_feeds import FeedContinuityError, write_unified_feeds
from radar.storage.history_store import ProjectHistoryEvent


def _project_event() -> ProjectHistoryEvent:
    return ProjectHistoryEvent(
        project="vLLM",
        category=Category.MODEL_SERVING,
        change_type=ChangeType.PROMOTED,
        ring=Ring.ADOPT,
        previous_ring=Ring.PILOT,
        run_id="run-legacy",
        observed_at=datetime(2026, 7, 30, 8, tzinfo=UTC),
        reasons=["production evidence improved"],
    )


def _intelligence_event() -> IntelligenceEvent:
    return IntelligenceEvent.for_lifecycle(
        release_id="release:legacy:kimi-k3",
        from_state=LifecycleState.VERIFIED,
        to_state=LifecycleState.QUALIFIED,
        occurred_at=datetime(2026, 7, 31, 8, tzinfo=UTC),
        evidence_ids=["evidence:kimi"],
    )


def test_unified_feed_keeps_legacy_ring_events_when_intelligence_is_empty(
    tmp_path,
) -> None:
    write_unified_feeds(
        tmp_path,
        project_events=[_project_event()],
        intelligence_events=[],
        site_title="Radar",
        base_url="https://example.test/radar",
    )

    rss = ElementTree.fromstring((tmp_path / "changes.rss").read_text())
    assert len(rss.findall("./channel/item")) == 1
    assert "vLLM" in rss.findtext("./channel/item/title", default="")
    assert (tmp_path / "changes.atom").read_bytes() == (
        tmp_path / "changes.xml"
    ).read_bytes()


def test_unified_feed_merges_event_families_newest_first(tmp_path) -> None:
    intelligence = _intelligence_event()
    write_unified_feeds(
        tmp_path,
        project_events=[_project_event()],
        intelligence_events=[intelligence],
        site_title="Radar",
        base_url="https://example.test/radar",
    )

    payload = json.loads((tmp_path / "changes.json").read_text())
    assert [item["id"] for item in payload["items"]] == [
        intelligence.id,
        "run-legacy:vLLM:promoted",
    ]
    assert payload["items"][0]["title"] == "release.qualified"


def test_unified_feed_fails_closed_if_backing_history_projects_no_items(
    tmp_path,
) -> None:
    with pytest.raises(FeedContinuityError, match="backing history"):
        write_unified_feeds(
            tmp_path,
            project_events=[],
            intelligence_events=[],
            site_title="Radar",
            base_url="",
            backing_event_count=1,
        )
