"""Append-only JSONL history log — the durable, portable source of truth.

The SQLite database is a fast queryable *projection*; this plain JSON Lines file
is what actually persists the timeline. It needs no service, is human-readable,
diffs cleanly, and can be committed, backed up, or synced however a self-hoster
likes. If the database is ever lost, the timeline is rebuilt from this file.

One JSON object per line, append-only — events are never rewritten or removed.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from radar.storage.history_store import ProjectHistoryEvent


logger = logging.getLogger(__name__)


def append_events(path: Path, events: list[ProjectHistoryEvent]) -> None:
    """Append events to the log as JSON lines. No-op for an empty list."""
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(event.model_dump(mode="json"), ensure_ascii=False) for event in events]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def load_events(path: Path) -> list[ProjectHistoryEvent]:
    """Read all events from the log, oldest-first. Missing file → empty list.

    Corrupt lines (a truncated tail after a crash mid-append, a bad hand edit)
    are skipped with a warning — one broken line must never make the whole
    timeline, and with it every future scan, unloadable.
    """
    if not path.exists():
        return []
    events: list[ProjectHistoryEvent] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                events.append(ProjectHistoryEvent.model_validate_json(line))
            except ValueError as exc:
                logger.warning(
                    "Skipping corrupt history line %d in %s: %s", line_no, path, exc
                )
    return events
