"""Append-only JSONL history log — the durable, portable source of truth.

The SQLite database is a fast queryable *projection*; this plain JSON Lines file
is what actually persists the timeline. It needs no service, is human-readable,
diffs cleanly, and can be committed, backed up, or synced however a self-hoster
likes. If the database is ever lost, the timeline is rebuilt from this file.

One JSON object per line, append-only — events are never rewritten or removed.
"""

from __future__ import annotations

import json
from pathlib import Path

from radar.storage.history_store import ProjectHistoryEvent


def append_events(path: Path, events: list[ProjectHistoryEvent]) -> None:
    """Append events to the log as JSON lines. No-op for an empty list."""
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(event.model_dump(mode="json"), ensure_ascii=False) for event in events]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def load_events(path: Path) -> list[ProjectHistoryEvent]:
    """Read all events from the log, oldest-first. Missing file → empty list."""
    if not path.exists():
        return []
    events: list[ProjectHistoryEvent] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            events.append(ProjectHistoryEvent.model_validate_json(line))
    return events
