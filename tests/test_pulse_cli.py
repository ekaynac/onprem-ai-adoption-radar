"""The ``radar pulse`` commands end to end, with every network call mocked."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from radar.cli import app
from radar.pulse import env
from radar.pulse.health import HEALTH_PATH, load_health
from radar.pulse.items import Lane, PulseItem
from radar.pulse.pipeline import ITEMS_PATH
from radar.pulse.store import load_items, save_items
from radar.pulse.triage import LABELS_PATH, load_labels
from radar.pulse.view import validate_view


RSS = ("<?xml version='1.0'?><rss version='2.0'><channel><title>t</title>"
       "<item><title>Introducing Model X</title><link>https://lab.example/x</link>"
       f"<pubDate>{format_datetime(datetime.now(UTC) - timedelta(days=1))}</pubDate></item>"
       "</channel></rss>")
runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("TYPESAFE_API_KEY", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "GITHUB_TOKEN",
                "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_ALERT_BOT_TOKEN",
                "RADAR_STATE_DIR"):
        monkeypatch.delenv(key, raising=False)


def _mock_network(monkeypatch: pytest.MonkeyPatch, handler) -> list[str]:
    seen: list[str] = []
    real = httpx.AsyncClient

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return handler(request)

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return real(*args, transport=httpx.MockTransport(recording), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return seen


def _sources(request: httpx.Request) -> httpx.Response:
    url = request.url
    recent = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    if url.host == "huggingface.co" and url.path == "/api/models":
        return httpx.Response(200, json=[
            {"id": "Qwen/Qwen4-8B", "createdAt": recent, "likes": 5, "tags": []}])
    if url.path == "/api/daily_papers":
        return httpx.Response(200, json=[
            {"paper": {"id": "2611.00001", "title": "A paper", "publishedAt": recent, "upvotes": 3}}])
    if url.host == "api.github.com":
        return httpx.Response(200, json={"items": [
            {"full_name": "new/tool", "created_at": recent, "stargazers_count": 300}]})
    if url.host == "hn.algolia.com":
        return httpx.Response(200, json={"hits": []})
    if url.path.endswith("README.md"):
        return httpx.Response(404)
    return httpx.Response(200, text=RSS)


def test_collect_fetches_every_lane_and_records_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_network(monkeypatch, _sources)

    result = runner.invoke(app, ["pulse", "collect", "--root", str(tmp_path)])

    assert result.exit_code == 0, result.output
    lanes = {item.lane for item in load_items(tmp_path / ITEMS_PATH)}
    assert lanes == {Lane.MODEL, Lane.PAPER, Lane.REPO, Lane.NEWS}
    health = load_health(tmp_path / HEALTH_PATH)
    assert set(health) == {"huggingface:lab-models", "huggingface:daily-papers",
                           "github:new-repos", "news:feeds"}
    assert all(entry["status"] == "ok" for entry in health.values())


def test_collect_fails_loudly_when_every_source_is_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_network(monkeypatch, lambda request: httpx.Response(404))

    result = runner.invoke(app, ["pulse", "collect", "--root", str(tmp_path)])

    assert result.exit_code == 1
    assert "Every Pulse source failed" in result.output
    assert load_health(tmp_path / HEALTH_PATH)["news:feeds"]["status"] == "error"


def _seed(root: Path) -> None:
    now = datetime.now(UTC)
    save_items(root / ITEMS_PATH, [
        PulseItem(lane=Lane.NEWS, key="news:1", title="Introducing Model X",
                  url="https://lab.example/x", source="openai-news",
                  first_seen=now, last_seen=now, summary="A new open model."),
        PulseItem(lane=Lane.MODEL, key="Qwen/Qwen4-8B", title="Qwen4-8B",
                  url="https://huggingface.co/Qwen/Qwen4-8B", source="huggingface",
                  first_seen=now, last_seen=now, kind="original", signals={"likes": 50}),
    ])


def test_triage_without_a_key_labels_with_rules(tmp_path: Path) -> None:
    _seed(tmp_path)

    result = runner.invoke(app, ["pulse", "triage", "--root", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "TYPESAFE_API_KEY not set" in result.output
    labels = load_labels(tmp_path / LABELS_PATH)
    assert {label.engine for label in labels.values()} == {"rules"}


def test_top_explains_each_position_and_rejects_unknown_lanes(tmp_path: Path) -> None:
    _seed(tmp_path)

    shown = runner.invoke(app, ["pulse", "top", "--root", str(tmp_path), "--lane", "model"])
    bad = runner.invoke(app, ["pulse", "top", "--root", str(tmp_path), "--lane", "gossip"])

    assert shown.exit_code == 0 and "Qwen4-8B" in shown.output and "original" in shown.output
    assert bad.exit_code != 0


def test_export_writes_a_valid_view_feeds_and_the_frontend(tmp_path: Path) -> None:
    _seed(tmp_path)
    frontend = tmp_path / "frontend-build"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<!doctype html><title>Pulse</title>", encoding="utf-8")
    (frontend / "assets" / "app.js").write_text("", encoding="utf-8")
    out = tmp_path / "_site"

    result = runner.invoke(app, ["pulse", "export", "--root", str(tmp_path), "--out", str(out),
                                 "--frontend", str(frontend), "--base-url", "https://x.example/r"])

    assert result.exit_code == 0, result.output
    view = validate_view(json.loads((out / "data" / "pulse.v1.json").read_text(encoding="utf-8")))
    assert [lane["lane"] for lane in view["lanes"]] == ["model", "paper", "repo", "news"]
    assert (out / "404.html").exists() and (out / "assets" / "app.js").exists()
    assert "<link>https://x.example/r" in (out / "pulse.xml").read_text(encoding="utf-8")


def test_export_refuses_without_a_built_frontend(tmp_path: Path) -> None:
    result = runner.invoke(app, ["pulse", "export", "--root", str(tmp_path),
                                 "--out", str(tmp_path / "_site"),
                                 "--frontend", str(tmp_path / "missing")])

    assert result.exit_code == 1
    assert "npm run build" in " ".join(result.output.split())


def test_telegram_dry_run_prints_and_records_nothing(tmp_path: Path) -> None:
    _seed(tmp_path)

    result = runner.invoke(app, ["pulse", "telegram", "--root", str(tmp_path), "--dry-run",
                                 "--site-url", "https://x.example/r/"])

    assert result.exit_code == 0, result.output
    assert "AI Radar Pulse" in result.output and "Qwen4-8B" in result.output
    assert not (tmp_path / "data" / "pulse" / "telegram-state.json").exists()


def test_telegram_without_secrets_in_ci_is_a_visible_skip(tmp_path: Path) -> None:
    result = runner.invoke(app, ["pulse", "telegram", "--root", str(tmp_path),
                                 "--skip-without-credentials", "--not-before-hour", "0"])

    assert result.exit_code == 0
    assert "Telegram digest skipped" in result.output


def test_watchdog_dry_run_reports_a_stale_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = {"schema_version": "pulse-v1", "generated_at": "2026-01-01T00:00:00+00:00",
             "lanes": [], "health": {"sources": [], "engines": {}, "degraded": False}}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("pulse.v1.json"):
            return httpx.Response(200, json=stale)
        return httpx.Response(200, json={"workflow_runs": []})

    _mock_network(monkeypatch, handler)

    result = runner.invoke(app, ["pulse", "watchdog", "--root", str(tmp_path), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "site" in result.output.casefold()
    assert not (tmp_path / "data" / "pulse" / "watchdog-state.json").exists()


def test_dotenv_fills_only_unset_variables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text(
        "# comment\nHF_TOKEN='hf_from_file'\nGITHUB_TOKEN=gh_from_file\nnot a pair\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_TOKEN", "gh_from_env")

    assert env.hf_headers(tmp_path) == {"Authorization": "Bearer hf_from_file"}
    assert env.github_headers(tmp_path)["Authorization"] == "Bearer gh_from_env"
    assert env.secret("MISSING", tmp_path) is None
