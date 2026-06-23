"""Tests for per-project momentum and the movers summary."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.models import Category, Ring
from radar.pipeline.delta import CardDelta, ChangeType
from radar.pipeline.momentum import compute_momentum
from radar.reports.movers import build_mover_lines
from radar.storage.history_store import ProjectHistoryEvent
from radar.storage.metrics_store import ProjectMetrics


def _row(day: int, stars: int) -> ProjectMetrics:
    return ProjectMetrics(
        project="vLLM",
        run_id=f"run-{day}",
        observed_at=datetime(2026, 6, day, tzinfo=UTC),
        stars=stars,
    )


def _event(day: int, change: ChangeType, ring: Ring) -> ProjectHistoryEvent:
    return ProjectHistoryEvent(
        project="vLLM",
        category=Category.MODEL_SERVING,
        change_type=change,
        ring=ring,
        run_id=f"run-{day}",
        observed_at=datetime(2026, 6, day, tzinfo=UTC),
    )


def test_recent_promotion_means_rising():
    momentum = compute_momentum(
        "vLLM",
        metric_rows=[_row(10, 1000), _row(12, 1001)],
        ring_events=[
            _event(1, ChangeType.NEW, Ring.WATCH),
            _event(12, ChangeType.PROMOTED, Ring.PILOT),
        ],
    )

    assert momentum.direction == "rising"
    assert "promoted" in momentum.note.lower()


def test_recent_demotion_means_falling():
    momentum = compute_momentum(
        "vLLM",
        metric_rows=[],
        ring_events=[_event(12, ChangeType.DEMOTED, Ring.WATCH)],
    )

    assert momentum.direction == "falling"


def test_strong_star_growth_means_rising():
    momentum = compute_momentum(
        "vLLM",
        metric_rows=[_row(1, 1000), _row(12, 1050)],  # +5%
        ring_events=[_event(1, ChangeType.NEW, Ring.PILOT)],
    )

    assert momentum.direction == "rising"
    assert momentum.star_growth_pct == 5.0


def test_flat_metrics_mean_steady():
    momentum = compute_momentum(
        "vLLM",
        metric_rows=[_row(1, 1000), _row(12, 1002)],
        ring_events=[_event(1, ChangeType.NEW, Ring.PILOT)],
    )

    assert momentum.direction == "steady"


def test_no_data_means_steady():
    momentum = compute_momentum("vLLM", metric_rows=[], ring_events=[])

    assert momentum.direction == "steady"


def test_old_ring_change_defers_to_star_trend():
    """A promotion many scans ago should not pin 'rising' forever."""
    momentum = compute_momentum(
        "vLLM",
        metric_rows=[_row(d, 1000) for d in (8, 9, 10, 11, 12)],
        ring_events=[
            _event(1, ChangeType.PROMOTED, Ring.PILOT),
            _event(8, ChangeType.UPDATED, Ring.PILOT),
            _event(9, ChangeType.UPDATED, Ring.PILOT),
            _event(10, ChangeType.UPDATED, Ring.PILOT),
            _event(11, ChangeType.UPDATED, Ring.PILOT),
        ],
    )

    assert momentum.direction == "steady"


def test_download_growth_means_rising_when_stars_flat():
    rows = [
        ProjectMetrics(project="vLLM", run_id="r1", observed_at=datetime(2026, 6, 1, tzinfo=UTC),
                       stars=1000, downloads_weekly=100_000),
        ProjectMetrics(project="vLLM", run_id="r2", observed_at=datetime(2026, 6, 12, tzinfo=UTC),
                       stars=1000, downloads_weekly=130_000),  # +30%
    ]
    momentum = compute_momentum("vLLM", metric_rows=rows, ring_events=[])
    assert momentum.direction == "rising"
    assert "downloads" in momentum.note.lower()


def test_paper_mention_rise_means_rising():
    rows = [
        ProjectMetrics(project="vLLM", run_id="r1", observed_at=datetime(2026, 6, 1, tzinfo=UTC),
                       paper_mentions=0),
        ProjectMetrics(project="vLLM", run_id="r2", observed_at=datetime(2026, 6, 12, tzinfo=UTC),
                       paper_mentions=4),  # +4 across the window
    ]
    momentum = compute_momentum("vLLM", metric_rows=rows, ring_events=[])
    assert momentum.direction == "rising"
    assert "paper" in momentum.note.lower()
    assert momentum.star_growth_pct is None  # no star data, yet still rising


def test_single_paper_mention_increase_stays_steady():
    rows = [
        ProjectMetrics(project="vLLM", run_id="r1", observed_at=datetime(2026, 6, 1, tzinfo=UTC),
                       paper_mentions=1),
        ProjectMetrics(project="vLLM", run_id="r2", observed_at=datetime(2026, 6, 12, tzinfo=UTC),
                       paper_mentions=2),  # +1 < MENTION_RISE_ABS
    ]
    assert compute_momentum("vLLM", metric_rows=rows, ring_events=[]).direction == "steady"


def test_mover_lines_surface_non_star_rising():
    rows = [
        ProjectMetrics(project="SGLang", run_id="r1", observed_at=datetime(2026, 6, 1, tzinfo=UTC),
                       paper_mentions=0),
        ProjectMetrics(project="SGLang", run_id="r2", observed_at=datetime(2026, 6, 12, tzinfo=UTC),
                       paper_mentions=3),
    ]
    momentum = compute_momentum("SGLang", metric_rows=rows, ring_events=[])
    lines = build_mover_lines([], [momentum])
    assert any("SGLang" in line and "rising" in line and "Paper" in line for line in lines)


def _card(project: str, category: Category, ring: Ring):
    from radar.models import DecisionCard

    return DecisionCard(
        project=project, category=category, ring=ring,
        summary="s", workflow_fit={}, risk_level="low",
    )


def test_mover_lines_lead_with_ring_changes():
    deltas = [
        CardDelta(
            project="vLLM", category=Category.MODEL_SERVING,
            change_type=ChangeType.PROMOTED,
            previous_ring=Ring.PILOT, current_ring=Ring.ADOPT, reasons=[],
            card=_card("vLLM", Category.MODEL_SERVING, Ring.ADOPT),
        ),
        CardDelta(
            project="Aider", category=Category.CODING_AGENTS,
            change_type=ChangeType.DEMOTED,
            previous_ring=Ring.PILOT, current_ring=Ring.WATCH, reasons=[],
            card=_card("Aider", Category.CODING_AGENTS, Ring.WATCH),
        ),
    ]
    momentums = [
        compute_momentum("CrewAI", metric_rows=[_row(1, 1000), _row(12, 1100)], ring_events=[]),
    ]

    lines = build_mover_lines(deltas, momentums)

    joined = "\n".join(lines)
    assert "vLLM" in joined and "pilot → adopt" in joined
    assert "Aider" in joined and "pilot → watch" in joined
    assert any("CrewAI" in line and "+10.0%" in line for line in lines)


def test_mover_lines_empty_when_nothing_moved():
    assert build_mover_lines([], []) == []
