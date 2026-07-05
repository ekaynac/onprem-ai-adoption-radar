"""Append-only JSONL audit log of autopilot promotions."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.storage.autopilot_log import AutopilotEntry, append_autopilot, load_autopilot


def _entry(repo: str) -> AutopilotEntry:
    return AutopilotEntry(
        repo=repo, source_id=f"github-{repo.split('/')[-1]}", category="model_serving",
        stars=1050, avg_velocity=41.7, added_at=datetime(2026, 7, 6, tzinfo=UTC),
    )


def test_append_and_load_round_trip(tmp_path: Path):
    path = tmp_path / "autopilot-log.jsonl"

    append_autopilot(path, [_entry("acme/rocket")])
    append_autopilot(path, [_entry("beta/engine")])
    append_autopilot(path, [])  # no-op

    rows = load_autopilot(path)
    assert [r.repo for r in rows] == ["acme/rocket", "beta/engine"]
    assert rows[0].avg_velocity == 41.7


def test_load_missing_returns_empty(tmp_path: Path):
    assert load_autopilot(tmp_path / "nope.jsonl") == []


def test_load_skips_corrupt_lines(tmp_path: Path):
    path = tmp_path / "autopilot-log.jsonl"
    append_autopilot(path, [_entry("acme/rocket")])
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{broken\n")

    assert len(load_autopilot(path)) == 1
