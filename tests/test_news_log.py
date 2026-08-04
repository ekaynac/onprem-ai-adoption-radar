"""News stores: round-trip, write-time id-dedupe, corrupt lines, UTC."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.storage.news_log import (
    NewsClassification,
    NewsItem,
    append_news_classifications,
    append_news_items,
    load_news_classifications,
    load_news_items,
    news_id_for,
)


NOW = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)


def _item(url: str = "https://example.com/a") -> NewsItem:
    return NewsItem(
        id=news_id_for(url),
        source_id="vllm-blog",
        title="vLLM v0.10 released",
        url=url,
        summary="Release notes",
        published_at=NOW,
        observed_at=NOW,
    )


def _classification(news_id: str) -> NewsClassification:
    return NewsClassification(
        news_id=news_id,
        relevant=True,
        event_type="release",
        components=["vllm"],
        operational_impact="improvement",
        summary="New release worth adopting.",
        citation="https://example.com/a",
        model="claude-opus-5",
        classified_at=NOW,
    )


def test_items_round_trip_and_dedupe(tmp_path):
    path = tmp_path / "news-observations.jsonl"
    assert append_news_items(path, [_item(), _item()]) == 1
    assert append_news_items(path, [_item()]) == 0
    assert (
        append_news_items(path, [_item("https://example.com/b")]) == 1
    )
    items = load_news_items(path)
    assert len(items) == 2
    assert items[0].title == "vLLM v0.10 released"


def test_items_skip_corrupt_lines(tmp_path):
    path = tmp_path / "news-observations.jsonl"
    append_news_items(path, [_item()])
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    assert len(load_news_items(path)) == 1


def test_naive_datetimes_become_utc():
    item = NewsItem(
        id="news:x",
        source_id="s",
        title="t",
        url="https://example.com",
        published_at=datetime(2026, 8, 1, 12, 0),
        observed_at=datetime(2026, 8, 4, 10, 0),
    )
    assert item.published_at is not None
    assert item.published_at.tzinfo is UTC
    assert item.observed_at.tzinfo is UTC


def test_missing_files_load_empty(tmp_path):
    assert load_news_items(tmp_path / "nope.jsonl") == []
    assert load_news_classifications(tmp_path / "nope.jsonl") == []


def test_classifications_dedupe_by_news_id(tmp_path):
    path = tmp_path / "news-classified.jsonl"
    row = _classification("news:1")
    assert append_news_classifications(path, [row, row]) == 1
    assert append_news_classifications(path, [row]) == 0
    assert (
        append_news_classifications(path, [_classification("news:2")]) == 1
    )
    assert len(load_news_classifications(path)) == 2


def test_news_id_is_stable_and_prefixed():
    assert news_id_for("https://example.com/a") == news_id_for(
        " https://example.com/a "
    )
    assert news_id_for("https://example.com/a").startswith("news:")
