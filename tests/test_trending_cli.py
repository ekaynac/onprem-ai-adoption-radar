"""CLI: radar trending scan / list."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from radar.cli import app
from radar.discovery.trending_entities import Lane, TrendingObservation
from radar.storage.trending_observations_log import append_observations, load_observations


def _obs(repo: str, stars: int, day: int, lane: Lane = Lane.ONPREM,
         created: str = "2026-06-01") -> TrendingObservation:
    return TrendingObservation(
        repo=repo, lane=lane, stars=stars,
        observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
        repo_created_at=datetime.fromisoformat(created).replace(tzinfo=UTC),
        topics=["llm"], license="MIT",
    )


def _seed(root: Path, rows: list[TrendingObservation]) -> None:
    (root / "data").mkdir(parents=True, exist_ok=True)
    append_observations(root / "data" / "trending-observations.jsonl", rows)


def test_trending_scan_appends_observations(tmp_path, monkeypatch):
    async def _fake_sweep(tracked_sources, client, now, headers=None):
        return [_obs("acme/rocket", 1500, 5)]

    monkeypatch.setattr("radar.discovery.trending_sweep.sweep_trending", _fake_sweep)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    runner = CliRunner()

    result = runner.invoke(app, ["trending", "scan", "--root", str(tmp_path)])

    assert result.exit_code == 0
    assert "1 trending repo" in result.stdout
    rows = load_observations(tmp_path / "data" / "trending-observations.jsonl")
    assert rows[0].repo == "acme/rocket"


def test_trending_scan_survives_missing_config(tmp_path, monkeypatch):
    async def _fake_sweep(tracked_sources, client, now, headers=None):
        assert tracked_sources == []  # missing config → empty tracked list
        return []

    monkeypatch.setattr("radar.discovery.trending_sweep.sweep_trending", _fake_sweep)
    runner = CliRunner()

    result = runner.invoke(app, ["trending", "scan", "--root", str(tmp_path)])

    assert result.exit_code == 0


def test_trending_list_shows_velocity_and_new(tmp_path):
    _seed(tmp_path, [
        _obs("fast/repo", 100, 1), _obs("fast/repo", 400, 4),
        _obs("new/repo", 60, 4, created="2026-07-01"),
    ])
    runner = CliRunner()

    result = runner.invoke(app, ["trending", "list", "--root", str(tmp_path)])

    assert result.exit_code == 0
    assert "fast/repo" in result.stdout
    assert "NEW" in result.stdout  # new/repo flagged


def test_trending_list_filters_by_lane(tmp_path):
    _seed(tmp_path, [
        _obs("on/repo", 100, 4, lane=Lane.ONPREM),
        _obs("broad/repo", 200, 4, lane=Lane.BROADER),
    ])
    runner = CliRunner()

    result = runner.invoke(app, ["trending", "list", "--root", str(tmp_path),
                                 "--lane", "broader"])

    assert result.exit_code == 0
    assert "broad/repo" in result.stdout and "on/repo" not in result.stdout


def test_trending_list_empty_store(tmp_path):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    runner = CliRunner()

    result = runner.invoke(app, ["trending", "list", "--root", str(tmp_path)])

    assert result.exit_code == 0
    assert "No trending observations yet" in result.stdout


def test_trending_list_rejects_unknown_lane(tmp_path):
    _seed(tmp_path, [_obs("on/repo", 100, 4)])
    runner = CliRunner()

    result = runner.invoke(app, ["trending", "list", "--root", str(tmp_path),
                                 "--lane", "bogus"])

    assert result.exit_code == 1
    assert "Unknown --lane" in result.output
