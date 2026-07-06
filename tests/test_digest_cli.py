"""radar digest generate."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from radar.cli import app
from radar.discovery.trending_entities import Lane, TrendingObservation
from radar.storage.digest_log import load_digests
from radar.storage.trending_observations_log import append_observations


def _seed_trending(root: Path) -> None:
    (root / "data").mkdir(parents=True, exist_ok=True)
    append_observations(root / "data" / "trending-observations.jsonl", [
        TrendingObservation(repo="acme/rocket", lane=Lane.ONPREM, stars=stars,
                            observed_at=datetime(2026, 7, day, 7, 0, tzinfo=UTC),
                            repo_created_at=datetime(2026, 6, 1, tzinfo=UTC),
                            description="d", topics=["llm"], license="MIT")
        for day, stars in ((1, 100), (4, 400))
    ])


def test_digest_generate_writes_page_cards_feeds_log(tmp_path):
    _seed_trending(tmp_path)
    result = CliRunner().invoke(app, ["digest", "generate", "--root", str(tmp_path)])

    assert result.exit_code == 0
    digests = tmp_path / "digests"
    assert list(digests.glob("digest_*.html"))          # dated page
    assert (digests / "digest.xml").exists() and (digests / "digest-rss.xml").exists()
    assert list((digests / "cards").glob("trending_*.svg"))
    log = load_digests(tmp_path / "data" / "digest-log.jsonl")
    assert len(log) == 1


def test_digest_generate_is_idempotent_per_week(tmp_path):
    _seed_trending(tmp_path)
    runner = CliRunner()
    runner.invoke(app, ["digest", "generate", "--root", str(tmp_path)])
    runner.invoke(app, ["digest", "generate", "--root", str(tmp_path)])

    log = load_digests(tmp_path / "data" / "digest-log.jsonl")
    assert len(log) == 1   # same ISO week → no duplicate log row
