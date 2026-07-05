"""CLI: radar trending promote (validate-or-abort append + audit log)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from radar.cli import app
from radar.discovery.trending_entities import Lane, TrendingObservation
from radar.storage.autopilot_log import load_autopilot
from radar.storage.config import load_config
from radar.storage.trending_observations_log import append_observations


_SEED = """version: "1.0"
sources:
  - id: github-cline
    type: github_repo
    enabled: true
    project: Cline
    category: coding_agents
    url: https://github.com/cline/cline
    tags: [coding-agent]
quotas:
  coding_agents: 4
"""


def _sustained(repo: str, stars_end: int = 1050, lane: Lane = Lane.ONPREM,
               license: str | None = "Apache-2.0",
               topics: list[str] | None = None) -> list[TrendingObservation]:
    days = [(1, 800), (4, 900), (6, stars_end)]
    return [
        TrendingObservation(
            repo=repo, lane=lane, stars=stars,
            observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
            repo_created_at=datetime(2026, 1, 1, tzinfo=UTC),
            description="fast llm serving", topics=topics or ["llm-inference"],
            license=license,
        )
        for day, stars in days
    ]


def _project(tmp_path: Path, observations: list[TrendingObservation]) -> Path:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "seed-sources.yaml").write_text(_SEED, encoding="utf-8")
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    append_observations(tmp_path / "data" / "trending-observations.jsonl", observations)
    return tmp_path


def test_promote_appends_and_logs(tmp_path):
    root = _project(tmp_path, _sustained("acme/rocket"))
    runner = CliRunner()

    result = runner.invoke(app, ["trending", "promote", "--root", str(root)])

    assert result.exit_code == 0
    assert "1 source" in result.stdout
    config = load_config(root / "config" / "seed-sources.yaml")
    added = [s for s in config.sources if s.id == "github-rocket"]
    assert added and "auto-added" in added[0].tags
    audit = load_autopilot(root / "data" / "autopilot-log.jsonl")
    assert audit[0].repo == "acme/rocket"


def test_promote_dry_run_writes_nothing(tmp_path):
    root = _project(tmp_path, _sustained("acme/rocket"))
    before = (root / "config" / "seed-sources.yaml").read_text(encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(app, ["trending", "promote", "--root", str(root), "--dry-run"])

    assert result.exit_code == 0
    assert (root / "config" / "seed-sources.yaml").read_text(encoding="utf-8") == before
    assert not (root / "data" / "autopilot-log.jsonl").exists()


def test_promote_skips_broader_lane_and_unqualified(tmp_path):
    observations = (
        _sustained("broad/repo", lane=Lane.BROADER)          # broader → never
        + _sustained("weak/repo", stars_end=805)             # flat → not sustained
    )
    root = _project(tmp_path, observations)
    runner = CliRunner()

    result = runner.invoke(app, ["trending", "promote", "--root", str(root)])

    assert result.exit_code == 0
    assert "No sources qualified" in result.stdout


def test_promote_respects_limit(tmp_path):
    observations = (
        _sustained("acme/rocket", stars_end=2000, topics=["llm-inference"])
        + _sustained("beta/serve", stars_end=1500, topics=["model-serving"])
    )
    root = _project(tmp_path, observations)
    runner = CliRunner()

    result = runner.invoke(app, ["trending", "promote", "--root", str(root), "--limit", "1"])

    assert result.exit_code == 0
    config = load_config(root / "config" / "seed-sources.yaml")
    auto = [s for s in config.sources if "auto-added" in s.tags]
    assert len(auto) == 1  # highest-velocity one only


def test_promote_missing_config_exits_1(tmp_path):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    append_observations(tmp_path / "data" / "trending-observations.jsonl",
                        _sustained("acme/rocket"))
    runner = CliRunner()

    result = runner.invoke(app, ["trending", "promote", "--root", str(tmp_path)])

    assert result.exit_code == 1
