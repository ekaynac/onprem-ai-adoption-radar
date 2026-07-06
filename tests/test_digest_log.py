"""Append-only JSONL log of generated digests (feed source)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from radar.storage.digest_log import DigestLogEntry, append_digest, load_digests


def _entry(label: str) -> DigestLogEntry:
    return DigestLogEntry(label=label, generated_at=datetime(2026, 7, 8, tzinfo=UTC),
                          url=f"digests/digest_{label}.html", summary=f"Week {label}")


def test_round_trip_and_noop_empty(tmp_path: Path):
    path = tmp_path / "digest-log.jsonl"
    append_digest(path, [_entry("2026-W27")])
    append_digest(path, [_entry("2026-W28")])
    append_digest(path, [])

    rows = load_digests(path)
    assert [r.label for r in rows] == ["2026-W27", "2026-W28"]


def test_missing_and_corrupt(tmp_path: Path):
    assert load_digests(tmp_path / "nope.jsonl") == []
    path = tmp_path / "digest-log.jsonl"
    append_digest(path, [_entry("2026-W28")])
    with path.open("a", encoding="utf-8") as h:
        h.write("{broken\n")
    assert len(load_digests(path)) == 1
