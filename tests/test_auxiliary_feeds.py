from __future__ import annotations

import json
from datetime import UTC, datetime

from radar.models import Ring
from radar.models_radar.history import ModelHistoryEvent
from radar.reports.auxiliary_feeds import write_auxiliary_feeds
from radar.research_radar.entities import TechniqueDomain
from radar.research_radar.history import TechniqueHistoryEvent
from radar.storage.digest_log import DigestLogEntry
from radar.storage.history_store import ChangeType


NOW = datetime(2026, 7, 31, tzinfo=UTC)


def test_one_writer_publishes_model_research_and_digest_feeds(tmp_path) -> None:
    model_event = ModelHistoryEvent(
        model_id="kimi-k3",
        family="Kimi",
        change_type=ChangeType.NEW,
        ring=Ring.WATCH,
        run_id="run-model",
        observed_at=NOW,
    )
    technique_event = TechniqueHistoryEvent(
        technique_id="speculative-decoding",
        domain=TechniqueDomain.INFERENCE,
        change_type=ChangeType.NEW,
        ring=Ring.ADOPT,
        run_id="run-research",
        observed_at=NOW,
    )
    digest = DigestLogEntry(
        label="2026-W31",
        generated_at=NOW,
        url="digests/digest_2026-W31.html",
        summary="Fresh architecture intelligence",
    )

    write_auxiliary_feeds(
        tmp_path,
        model_events=[model_event],
        technique_events=[technique_event],
        digests=[digest],
        site_title="Radar",
        base_url="https://example.test/radar/",
    )

    assert "kimi-k3" in (tmp_path / "changes-models.xml").read_text()
    assert "speculative-decoding" in (
        tmp_path / "changes-research.xml"
    ).read_text()
    assert json.loads((tmp_path / "changes-models.json").read_text())["items"]
    assert json.loads((tmp_path / "changes-research.json").read_text())["items"]
    assert "2026-W31" in (tmp_path / "digests" / "digest.xml").read_text()
    assert "https://example.test/radar/digests/digest-rss.xml" in (
        tmp_path / "digests" / "digest-rss.xml"
    ).read_text()
