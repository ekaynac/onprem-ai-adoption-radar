"""Weekly digest assembly (pure, deterministic)."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.discovery.trending_entities import Lane, TrendingEntry
from radar.models_radar.history import ModelHistoryEvent
from radar.reports.digest import build_digest, iso_week_bounds, week_label
from radar.storage.autopilot_log import AutopilotEntry
from radar.storage.history_log import ProjectHistoryEvent


# 2026-07-08 is a Wednesday in ISO week 28 (Mon 2026-07-06 .. Sun 2026-07-12).
NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


def _entry(repo, lane, vel=10.0):
    return TrendingEntry(repo=repo, lane=lane, stars=1000, velocity_per_day=vel,
                         is_new=False, first_seen="2026-07-01", description="d", topics=["llm"])


def _auto(repo, day):
    return AutopilotEntry(repo=repo, source_id=f"github-{repo.split('/')[-1]}",
                          category="model_serving", stars=1000, avg_velocity=40.0,
                          added_at=datetime(2026, 7, day, tzinfo=UTC))


def _tool_event(project, day):
    # Ring values are adopt|pilot|watch|avoid; ChangeType new|promoted|demoted|updated.
    return ProjectHistoryEvent(
        project=project, category="model_serving", change_type="new", ring="pilot",
        previous_ring=None, run_id="r1", observed_at=datetime(2026, 7, day, tzinfo=UTC),
        reasons=["seeded"],
    )


def test_iso_week_bounds_and_label():
    start, end = iso_week_bounds(NOW)
    assert start == datetime(2026, 7, 6, tzinfo=UTC)
    assert end == datetime(2026, 7, 13, tzinfo=UTC)
    assert week_label(NOW) == "2026-W28"


def test_build_digest_windows_and_caps():
    trending = ([_entry(f"on/{i}", Lane.ONPREM, vel=50 - i) for i in range(7)]
                + [_entry("broad/x", Lane.BROADER)])
    autopilot = [_auto("acme/rocket", 7),          # in week 28
                 _auto("old/repo", 1)]             # week 27 → excluded
    tool_events = [_tool_event("Cline", 7),        # in week
                   _tool_event("Old", 1)]          # excluded

    digest = build_digest(NOW, trending, autopilot, tool_events, [], [], top_n=5)

    assert digest.label == "2026-W28"
    assert len(digest.trending_onprem) == 5           # capped
    assert [e.repo for e in digest.trending_broader] == ["broad/x"]
    assert [a.repo for a in digest.auto_added] == ["acme/rocket"]   # windowed
    assert [c.name for c in digest.changes] == ["Cline"]            # windowed
    assert digest.changes[0].kind == "tool"


def test_build_digest_normalizes_all_three_event_kinds():
    model_ev = ModelHistoryEvent(
        model_id="qwen3-0.6b", family="Qwen3", change_type="promoted", ring="adopt",
        previous_ring="pilot", run_id="r1", observed_at=datetime(2026, 7, 7, tzinfo=UTC),
        reasons=[],
    )
    digest = build_digest(NOW, [], [], [_tool_event("Cline", 7)], [model_ev], [], top_n=5)

    kinds = {(c.kind, c.name) for c in digest.changes}
    assert ("tool", "Cline") in kinds
    assert ("model", "qwen3-0.6b") in kinds
    assert digest.summary_line  # non-empty
