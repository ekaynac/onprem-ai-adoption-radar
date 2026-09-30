"""Repo/news adapters over the existing observation logs, and the item store."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from radar.pulse.adapters import news_items, repo_items
from radar.pulse.items import Lane, PulseItem
from radar.pulse.store import load_items, merge_items, save_items


NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows) + "not json\n", encoding="utf-8")
    return path


def test_repo_items_keep_latest_observation_and_compute_velocity(tmp_path: Path) -> None:
    path = _write_jsonl(tmp_path / "trending.jsonl", [
        {"repo": "incoai/splash", "lane": "onprem", "stars": 400,
         "observed_at": "2026-09-28T08:00:00Z", "repo_created_at": "2026-09-20T12:00:00Z",
         "description": "A local inference engine for Apple silicon.", "topics": ["mlx"]},
        {"repo": "incoai/splash", "lane": "onprem", "stars": 924,
         "observed_at": "2026-09-30T08:00:00Z", "repo_created_at": "2026-09-20T12:00:00Z",
         "description": "A local inference engine for Apple silicon.", "topics": ["mlx"]},
        {"repo": "old/classic", "lane": "broader", "stars": 90000,
         "observed_at": "2026-09-30T08:00:00Z", "repo_created_at": "2019-01-01T00:00:00Z"},
    ])

    items = repo_items(path, NOW, window_days=14)

    assert [i.key for i in items] == ["incoai/splash"]  # created long ago → not new
    splash = items[0]
    assert splash.lane is Lane.REPO
    assert splash.signals["stars"] == 924
    assert splash.signals["stars_per_day"] == 92.4
    assert splash.first_seen == datetime(2026, 9, 28, 8, tzinfo=UTC)
    assert splash.tags == ("mlx",)


def test_news_items_dedupe_and_respect_window(tmp_path: Path) -> None:
    path = _write_jsonl(tmp_path / "news.jsonl", [
        {"id": "news:1", "source_id": "hf-blog", "title": "Fresh  post",
         "url": "https://huggingface.co/blog/x", "published_at": "2026-09-29T10:00:00Z",
         "observed_at": "2026-09-29T11:00:00Z"},
        {"id": "news:1", "source_id": "hf-blog", "title": "Fresh post",
         "url": "https://huggingface.co/blog/x", "published_at": "2026-09-29T10:00:00Z",
         "observed_at": "2026-09-29T13:00:00Z"},
        {"id": "news:2", "source_id": "hn-vllm", "title": "Ancient",
         "url": "https://example.com/a", "published_at": "2026-01-01T00:00:00Z",
         "observed_at": "2026-01-01T00:00:00Z"},
    ])

    items = news_items(path, NOW, window_days=14)

    assert [(i.key, i.title) for i in items] == [("news:1", "Fresh post")]


def test_missing_inputs_yield_no_items(tmp_path: Path) -> None:
    assert repo_items(tmp_path / "absent.jsonl", NOW, 14) == []
    assert news_items(tmp_path / "absent.jsonl", NOW, 14) == []


def _item(key: str, first_seen: datetime, likes: float, published: datetime | None = None):
    return PulseItem(
        lane=Lane.MODEL, key=key, title=key.split("/")[1],
        url=f"https://huggingface.co/{key}", source="huggingface",
        published_at=published, first_seen=first_seen, last_seen=first_seen,
        signals={"likes": likes},
    )


def test_merge_keeps_first_seen_takes_fresh_signals_and_prunes_window() -> None:
    day = timedelta(days=1)
    existing = [
        _item("Qwen/A", NOW - 3 * day, likes=10),
        _item("Qwen/Old", NOW - 30 * day, likes=5),
    ]
    incoming = [_item("Qwen/A", NOW, likes=99), _item("Qwen/B", NOW, likes=1)]

    merged = merge_items(existing, incoming, NOW, window_days=14)

    by_key = {i.key: i for i in merged}
    assert set(by_key) == {"Qwen/A", "Qwen/B"}
    assert by_key["Qwen/A"].first_seen == NOW - 3 * day
    assert by_key["Qwen/A"].signals["likes"] == 99
    # Inputs are untouched (immutable merge).
    assert existing[0].signals["likes"] == 10


def test_store_round_trips_and_skips_corrupt_lines(tmp_path: Path) -> None:
    path = tmp_path / "pulse" / "items.jsonl"
    items = [_item("Qwen/A", NOW, likes=1, published=NOW)]

    save_items(path, items)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{broken\n")

    assert load_items(path) == items
    assert not path.with_suffix(".jsonl.tmp").exists()
