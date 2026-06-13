"""Tests for ring overrides and the trial decision journal."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.models import Category, DecisionCard, Ring
from radar.storage.overrides_store import (
    OverridesStore,
    RingOverride,
    TrialRecord,
    apply_overrides,
)


NOW = datetime(2026, 6, 13, tzinfo=UTC)


def _card(project: str, ring: Ring) -> DecisionCard:
    return DecisionCard(
        project=project,
        category=Category.MODEL_SERVING,
        ring=ring,
        summary="s",
        workflow_fit={},
        risk_level="low",
    )


def test_set_and_load_override_round_trip(tmp_path: Path):
    store = OverridesStore(tmp_path / "overrides.yaml")

    store.set_override(
        RingOverride(project="vLLM", ring=Ring.AVOID, reason="failed sec review", set_at=NOW)
    )

    loaded = store.load()
    assert loaded.overrides[0].project == "vLLM"
    assert loaded.overrides[0].ring == Ring.AVOID


def test_set_override_replaces_existing_for_same_project(tmp_path: Path):
    store = OverridesStore(tmp_path / "overrides.yaml")
    store.set_override(RingOverride(project="vLLM", ring=Ring.AVOID, reason="a", set_at=NOW))
    store.set_override(RingOverride(project="vLLM", ring=Ring.WATCH, reason="b", set_at=NOW))

    loaded = store.load()

    assert len(loaded.overrides) == 1
    assert loaded.overrides[0].ring == Ring.WATCH


def test_clear_override(tmp_path: Path):
    store = OverridesStore(tmp_path / "overrides.yaml")
    store.set_override(RingOverride(project="vLLM", ring=Ring.AVOID, reason="a", set_at=NOW))

    removed = store.clear_override("vLLM")

    assert removed is True
    assert store.load().overrides == []
    assert store.clear_override("vLLM") is False


def test_add_trial_appends(tmp_path: Path):
    store = OverridesStore(tmp_path / "overrides.yaml")
    store.add_trial(
        TrialRecord(project="vLLM", outcome="adopted", notes="works", recorded_at=NOW)
    )
    store.add_trial(
        TrialRecord(project="Aider", outcome="rejected", notes="too slow", recorded_at=NOW)
    )

    loaded = store.load()

    assert [t.project for t in loaded.trials] == ["vLLM", "Aider"]


def test_missing_file_loads_empty(tmp_path: Path):
    loaded = OverridesStore(tmp_path / "overrides.yaml").load()

    assert loaded.overrides == [] and loaded.trials == []


def test_apply_overrides_pins_ring_and_notes_drift():
    cards = [_card("vLLM", Ring.ADOPT), _card("Aider", Ring.PILOT)]
    overrides = [
        RingOverride(project="vLLM", ring=Ring.AVOID, reason="failed sec review", set_at=NOW)
    ]

    result = apply_overrides(cards, overrides)

    pinned = next(c for c in result if c.project == "vLLM")
    assert pinned.ring == Ring.AVOID
    assert pinned.pinned is True
    assert pinned.pinned_reason == "failed sec review"
    assert pinned.computed_ring == Ring.ADOPT
    # Drift: the computed decision disagrees with the pin — say so visibly.
    assert any("adopt" in note for note in pinned.evidence_notes)
    # Untouched card stays untouched (and input not mutated).
    untouched = next(c for c in result if c.project == "Aider")
    assert untouched.pinned is False
    assert cards[0].ring == Ring.ADOPT


def test_apply_overrides_agreeing_pin_has_no_drift_note():
    cards = [_card("vLLM", Ring.AVOID)]
    overrides = [
        RingOverride(project="vLLM", ring=Ring.AVOID, reason="confirmed", set_at=NOW)
    ]

    result = apply_overrides(cards, overrides)

    assert result[0].pinned is True
    assert result[0].evidence_notes == []
