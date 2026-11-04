"""The item store: immutable merge inside the window, crash-safe persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from radar.pulse.items import Lane, PulseItem
from radar.pulse.store import load_items, merge_items, save_items


NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


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
