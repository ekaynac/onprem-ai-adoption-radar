"""Technique ring-change events + append-only JSONL log."""

from datetime import UTC, datetime

from radar.models import Category, Ring
from radar.research_radar.entities import OnPremImpact, TechniqueDomain, TechniqueEntry
from radar.research_radar.history import (
    TechniqueHistoryEvent,
    append_technique_events,
    diff_technique_rings,
    load_technique_events,
)
from radar.storage.history_store import ChangeType


NOW = datetime(2026, 7, 3, 10, 0, tzinfo=UTC)


def _entry(technique_id: str, ring: Ring | None) -> TechniqueEntry:
    return TechniqueEntry(
        id=technique_id, name=technique_id, category=Category.MODEL_SERVING,
        domain=TechniqueDomain.INFERENCE, onprem_impact=OnPremImpact.REDUCES_LATENCY,
        ring=ring,
    )


def test_new_promoted_demoted_and_unchanged():
    entries = [
        _entry("brand-new", Ring.WATCH),
        _entry("promoted", Ring.ADOPT),
        _entry("demoted", Ring.WATCH),
        _entry("unchanged", Ring.PILOT),
        _entry("unringed", None),
    ]
    previous = {"promoted": Ring.PILOT, "demoted": Ring.PILOT, "unchanged": Ring.PILOT}

    events = diff_technique_rings(entries, previous, "run-1", NOW)

    by_id = {e.technique_id: e for e in events}
    assert set(by_id) == {"brand-new", "promoted", "demoted"}
    assert by_id["brand-new"].change_type == ChangeType.NEW
    assert by_id["promoted"].change_type == ChangeType.PROMOTED
    assert by_id["promoted"].previous_ring == Ring.PILOT
    assert by_id["demoted"].change_type == ChangeType.DEMOTED


def test_append_and_load_roundtrip(tmp_path):
    path = tmp_path / "technique-history.jsonl"
    events: list[TechniqueHistoryEvent] = diff_technique_rings(
        [_entry("lora", Ring.ADOPT)], {}, "run-1", NOW
    )
    append_technique_events(path, events)
    append_technique_events(path, [])  # no-op, must not create noise

    loaded: list[TechniqueHistoryEvent] = load_technique_events(path)

    assert len(loaded) == 1
    assert loaded[0].technique_id == "lora"
    assert loaded[0].domain == TechniqueDomain.INFERENCE  # domain round-trips
    assert loaded[0].ring == Ring.ADOPT


def test_load_skips_corrupt_lines(tmp_path):
    path = tmp_path / "technique-history.jsonl"
    append_technique_events(
        path, diff_technique_rings([_entry("lora", Ring.ADOPT)], {}, "run-1", NOW)
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json}\n")

    assert len(load_technique_events(path)) == 1


def test_load_missing_file_returns_empty(tmp_path):
    assert load_technique_events(tmp_path / "nope.jsonl") == []
