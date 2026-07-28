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


def test_digest_page_links_up_one_level(tmp_path):
    _seed_trending(tmp_path)
    CliRunner().invoke(app, ["digest", "generate", "--root", str(tmp_path)])

    page = next((tmp_path / "digests").glob("digest_*.html")).read_text(encoding="utf-8")
    assert "../index.html" in page          # nav points up to the site root
    assert "../trending.html" in page
    assert "../static/brand/favicon.png" in page   # favicon resolves up one level
    assert 'href="index.html"' not in page  # no shallow root-relative link remains
    assert 'class="positioning"' in page
    assert (
        "Trending tells you what&#39;s hot. The radar tells you what to adopt "
        "— and what it takes to run it."
    ) in page


def test_digest_webhook_fires_once_per_week(tmp_path, monkeypatch):
    _seed_trending(tmp_path)
    # enable notify so the webhook path is live
    (tmp_path / "data" / "config.yaml").write_text(
        "sources:\n"
        "  - id: acme-rocket\n"
        "    type: github_repo\n"
        "    project: acme/rocket\n"
        "    category: coding_agents\n"
        "    url: https://github.com/acme/rocket\n"
        "notify:\n"
        "  enabled: true\n"
        "  webhook_url: https://example.test/hook\n",
        encoding="utf-8",
    )
    calls = []

    async def _fake_send(config, digest, client):
        calls.append(digest.label)
        return True

    monkeypatch.setattr("radar.notify.webhook.send_digest_notification", _fake_send)
    runner = CliRunner()

    runner.invoke(app, ["digest", "generate", "--root", str(tmp_path)])
    runner.invoke(app, ["digest", "generate", "--root", str(tmp_path)])  # same ISO week

    assert len(calls) == 1   # first run pings; second run (same week) does not re-ping
