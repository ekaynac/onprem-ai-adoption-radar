"""Append-only JSONL log for per-source signal counts — the durable source of truth.

`source_health` in SQLite is a fast queryable *projection*, same as the ring
history: this plain JSON Lines file is what actually persists per-scan source
outcomes. CI starts every run from an empty database, so without this log the
stale-feed detector (which needs several consecutive recorded scans) could
never accumulate evidence there. One JSON object per line, append-only.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel


logger = logging.getLogger(__name__)


class SourceOutcome(BaseModel):
    """A single source's result for one scan: how many signals, and how it went."""

    count: int
    status: str


class SourceHealthRecord(BaseModel):
    """One scan's source-health outcomes, keyed by source id."""

    run_id: str
    observed_at: datetime
    sources: dict[str, SourceOutcome]


def append_source_health(path: Path, record: SourceHealthRecord) -> None:
    """Append one scan's source-health record to the log as a JSON line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def load_source_health(path: Path) -> list[SourceHealthRecord]:
    """Read all source-health records from the log, oldest-first. Missing file → [].

    Corrupt lines (a truncated tail after a crash mid-append, a bad hand edit)
    are skipped with a warning — one broken line must never make the whole
    log, and with it rehydration of every future scan, unloadable.
    """
    if not path.exists():
        return []
    records: list[SourceHealthRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                records.append(SourceHealthRecord.model_validate_json(line))
            except ValueError as exc:
                logger.warning(
                    "Skipping corrupt source-health line %d in %s: %s", line_no, path, exc
                )
    return records
