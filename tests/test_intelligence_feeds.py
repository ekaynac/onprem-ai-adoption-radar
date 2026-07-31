import json
from datetime import UTC, datetime

import pytest

from radar.intelligence.contracts import LifecycleState
from radar.intelligence.events import IntelligenceEvent
from radar.reports.intelligence_feeds import (
    render_intelligence_atom,
    render_intelligence_json_feed,
    render_intelligence_rss,
)


def test_rss_atom_and_json_feed_share_item_id() -> None:
    events = [
        IntelligenceEvent.for_lifecycle(
            release_id="release:kimi-k3",
            from_state=LifecycleState.DETECTED,
            to_state=LifecycleState.VERIFIED,
            occurred_at=datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
            evidence_ids=["evidence:one"],
        )
    ]

    atom = render_intelligence_atom(events, "https://radar.example")
    rss = render_intelligence_rss(events, "https://radar.example")
    json_feed = json.loads(
        render_intelligence_json_feed(events, "https://radar.example")
    )

    expected = events[0].id
    assert expected in atom
    assert expected in rss
    assert json_feed["items"][0]["id"] == expected


def test_public_feed_rejects_workspace_scoped_events() -> None:
    event = IntelligenceEvent.for_lifecycle(
        release_id="release:kimi-k3",
        from_state=LifecycleState.DETECTED,
        to_state=LifecycleState.VERIFIED,
        occurred_at=datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
        evidence_ids=[],
    ).model_copy(update={"workspace_id": "workspace:private"})

    with pytest.raises(ValueError, match="workspace"):
        render_intelligence_json_feed([event], "https://radar.example")
