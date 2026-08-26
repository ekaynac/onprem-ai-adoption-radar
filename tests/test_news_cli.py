"""CLI: radar news scan / classify."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from radar.cli import app
from radar.discovery.news_sweep import NewsSweepResult
from radar.storage.news_log import (
    NewsClassification,
    NewsItem,
    append_news_items,
    load_news_classifications,
    load_news_items,
    news_id_for,
)


NOW = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)


def _item(url: str = "https://blog.vllm.ai/v0-10") -> NewsItem:
    return NewsItem(
        id=news_id_for(url),
        source_id="vllm-blog",
        title="vLLM v0.10 released",
        url=url,
        summary="Release notes",
        published_at=NOW,
        observed_at=NOW,
    )


def test_news_scan_appends_and_records_health(tmp_path, monkeypatch):
    async def _fake_sweep(config, client, now):
        return NewsSweepResult(
            items=[_item()],
            outcomes={"vllm-blog": {"count": 1, "status": "ok"}},
        )

    monkeypatch.setattr("radar.discovery.news_sweep.sweep_news", _fake_sweep)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    runner = CliRunner()

    result = runner.invoke(app, ["news", "scan", "--root", str(tmp_path)])

    assert result.exit_code == 0
    assert "1 new" in result.stdout
    rows = load_news_items(tmp_path / "data" / "news-observations.jsonl")
    assert rows[0].id == news_id_for("https://blog.vllm.ai/v0-10")
    health = (tmp_path / "data" / "source-health.jsonl").read_text(
        encoding="utf-8"
    )
    assert "news:vllm-blog" in health


def test_news_classify_skips_visibly_without_any_engine(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("shutil.which", lambda _name: None)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    runner = CliRunner()

    result = runner.invoke(app, ["news", "classify", "--root", str(tmp_path)])

    assert result.exit_code == 0
    assert "No classification engine available" in result.stdout
    assert not (tmp_path / "data" / "news-classified.jsonl").exists()


def test_news_classify_appends_only_unclassified(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    append_news_items(
        tmp_path / "data" / "news-observations.jsonl",
        [_item(), _item("https://ollama.com/blog/new-engine")],
    )

    def _fake_client():
        return object()

    def _fake_classify(items, config, client, now, *, root=None):
        from radar.discovery.news_classify import NewsClassifyResult

        rows = [
            NewsClassification(
                news_id=item.id,
                relevant=True,
                event_type="release",
                components=["vllm"],
                operational_impact="improvement",
                summary="s",
                citation=item.url,
                model=config.model,
                classified_at=now,
            )
            for item in items
        ]
        return NewsClassifyResult(classifications=rows)

    monkeypatch.setattr(
        "radar.discovery.news_classify.build_anthropic_client", _fake_client
    )
    monkeypatch.setattr(
        "radar.discovery.news_classify.classify_news", _fake_classify
    )
    runner = CliRunner()

    result = runner.invoke(app, ["news", "classify", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "Classified 2 item(s)" in result.stdout
    rows = load_news_classifications(
        tmp_path / "data" / "news-classified.jsonl"
    )
    assert len(rows) == 2

    # Second run: nothing left to classify — no extra API spend.
    result = runner.invoke(app, ["news", "classify", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "No unclassified news items" in result.stdout


def test_news_scan_uses_packaged_config_fallback(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    async def _fake_sweep(config, client, now):
        captured["config"] = config
        return NewsSweepResult()

    monkeypatch.setattr("radar.discovery.news_sweep.sweep_news", _fake_sweep)
    runner = CliRunner()

    result = runner.invoke(app, ["news", "scan", "--root", str(tmp_path)])

    assert result.exit_code == 0
    config = captured["config"]
    assert getattr(config, "version", None) == "1"
    packaged = Path("config/news-sources.yaml")
    assert packaged.exists()
