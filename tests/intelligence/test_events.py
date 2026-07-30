from datetime import UTC, datetime

import pytest

from radar.intelligence.contracts import LifecycleState
from radar.intelligence.database import Database
from radar.intelligence.event_log import EventLog
from radar.intelligence.events import IntelligenceEvent
from radar.intelligence.repositories import (
    RepositoryConflict,
    SqlAlchemyIntelligenceRepository,
)


NOW = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)


def test_event_id_is_stable_for_same_transition() -> None:
    event = IntelligenceEvent.for_lifecycle(
        release_id="release:kimi-k3",
        from_state=LifecycleState.DETECTED,
        to_state=LifecycleState.VERIFIED,
        occurred_at=NOW,
        evidence_ids=["evidence:one"],
    )

    assert event.id == IntelligenceEvent.for_lifecycle(
        release_id="release:kimi-k3",
        from_state=LifecycleState.DETECTED,
        to_state=LifecycleState.VERIFIED,
        occurred_at=NOW,
        evidence_ids=["evidence:one"],
    ).id


def test_event_is_append_only_and_round_trips_from_database(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'intelligence.db'}")
    database.create_schema()
    repository = SqlAlchemyIntelligenceRepository(database)
    event = IntelligenceEvent.for_lifecycle(
        release_id="release:kimi-k3",
        from_state=LifecycleState.DETECTED,
        to_state=LifecycleState.VERIFIED,
        occurred_at=NOW,
        evidence_ids=["evidence:one"],
    )

    assert repository.append_event(event) is True
    assert repository.append_event(event) is False

    assert repository.get_event(event.id) == event
    assert repository.list_events(limit=10) == [event]


def test_changed_payload_under_existing_event_id_is_rejected(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'intelligence.db'}")
    database.create_schema()
    repository = SqlAlchemyIntelligenceRepository(database)
    event = IntelligenceEvent.for_lifecycle(
        release_id="release:kimi-k3",
        from_state=LifecycleState.DETECTED,
        to_state=LifecycleState.VERIFIED,
        occurred_at=NOW,
        evidence_ids=[],
    )
    repository.append_event(event)

    with pytest.raises(RepositoryConflict, match="Event id changed"):
        repository.append_event(
            event.model_copy(update={"type": "release.qualified"})
        )


def test_public_event_log_is_idempotent_canonical_jsonl(tmp_path) -> None:
    event = IntelligenceEvent.for_lifecycle(
        release_id="release:kimi-k3",
        from_state=LifecycleState.DETECTED,
        to_state=LifecycleState.VERIFIED,
        occurred_at=NOW,
        evidence_ids=["evidence:two", "evidence:one"],
    )
    log = EventLog(tmp_path / "data" / "intelligence" / "events.jsonl")

    assert log.append(event) is True
    assert log.append(event) is False

    assert log.read() == [event]
    assert log.path.read_text(encoding="utf-8").count("\n") == 1
