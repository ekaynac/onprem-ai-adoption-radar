"""Tests for cross-run delta computation."""

from __future__ import annotations

from radar.models import Category, DecisionCard, Ring
from radar.pipeline.delta import ChangeType, CardDelta, compute_deltas


def _card(
    project: str,
    ring: Ring,
    category: Category = Category.CODING_AGENTS,
    what_changed: list[str] | None = None,
) -> DecisionCard:
    return DecisionCard(
        project=project,
        category=category,
        ring=ring,
        summary=f"{project} summary.",
        workflow_fit={"personal_dev": "high"},
        risk_level="low",
        what_changed=what_changed or [],
    )


def test_new_project_is_change_type_new() -> None:
    current = [_card("Aider", Ring.PILOT)]
    deltas = compute_deltas(previous=[], current=current)
    assert len(deltas) == 1
    assert deltas[0].project == "Aider"
    assert deltas[0].change_type is ChangeType.NEW
    assert deltas[0].previous_ring is None
    assert deltas[0].current_ring is Ring.PILOT


def test_ring_promotion_is_promoted() -> None:
    previous = [_card("Goose", Ring.WATCH)]
    current = [_card("Goose", Ring.PILOT)]
    deltas = compute_deltas(previous=previous, current=current)
    assert len(deltas) == 1
    delta = deltas[0]
    assert delta.change_type is ChangeType.PROMOTED
    assert delta.previous_ring is Ring.WATCH
    assert delta.current_ring is Ring.PILOT
    assert any("watch" in r.lower() and "pilot" in r.lower() for r in delta.reasons)


def test_ring_demotion_is_demoted() -> None:
    previous = [_card("RiskyTool", Ring.PILOT)]
    current = [_card("RiskyTool", Ring.AVOID)]
    deltas = compute_deltas(previous=previous, current=current)
    assert deltas[0].change_type is ChangeType.DEMOTED


def test_new_release_highlight_same_ring_is_updated() -> None:
    previous = [_card("vLLM", Ring.PILOT, what_changed=["Repo snapshot: 100 stars."])]
    current = [
        _card(
            "vLLM",
            Ring.PILOT,
            what_changed=["Repo snapshot: 120 stars.", "release: v0.9.0 adds FP8."],
        )
    ]
    deltas = compute_deltas(previous=previous, current=current)
    assert len(deltas) == 1
    delta = deltas[0]
    assert delta.change_type is ChangeType.UPDATED
    assert any("v0.9.0" in r for r in delta.reasons)


def test_only_snapshot_metric_drift_is_unchanged_and_excluded() -> None:
    previous = [_card("vLLM", Ring.PILOT, what_changed=["Repo snapshot: 100 stars."])]
    current = [_card("vLLM", Ring.PILOT, what_changed=["Repo snapshot: 101 stars."])]
    deltas = compute_deltas(previous=previous, current=current)
    assert deltas == []


def test_unchanged_card_is_excluded() -> None:
    card = _card("Stable", Ring.WATCH, what_changed=["release: v1 launched."])
    deltas = compute_deltas(previous=[card], current=[card])
    assert deltas == []


def test_compute_deltas_does_not_mutate_inputs() -> None:
    previous = [_card("Goose", Ring.WATCH)]
    current = [_card("Goose", Ring.PILOT)]
    prev_snapshot = [c.model_copy(deep=True) for c in previous]
    cur_snapshot = [c.model_copy(deep=True) for c in current]
    compute_deltas(previous=previous, current=current)
    assert previous == prev_snapshot
    assert current == cur_snapshot


def test_deltas_sorted_new_first_then_promoted() -> None:
    previous = [_card("Goose", Ring.WATCH)]
    current = [
        _card("Goose", Ring.PILOT),
        _card("BrandNew", Ring.ADOPT),
    ]
    deltas = compute_deltas(previous=previous, current=current)
    change_types = [d.change_type for d in deltas]
    assert change_types[0] is ChangeType.NEW
    assert ChangeType.PROMOTED in change_types
