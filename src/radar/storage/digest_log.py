"""Append-only JSONL log of generated digests — the newsletter feed source."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict


logger = logging.getLogger(__name__)


class DigestLogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    generated_at: datetime
    url: str
    summary: str


def append_digest(path: Path, entries: list[DigestLogEntry]) -> None:
    if not entries:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e.model_dump(mode="json"), ensure_ascii=False) for e in entries]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def load_digests(path: Path) -> list[DigestLogEntry]:
    if not path.exists():
        return []
    rows: list[DigestLogEntry] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_no, raw in enumerate(handle, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    rows.append(DigestLogEntry.model_validate_json(line))
                except ValueError as exc:
                    logger.warning("Skipping corrupt digest-log line %d in %s: %s",
                                   line_no, path, exc)
    except OSError as exc:
        logger.warning("Could not read digest log %s: %s", path, exc)
    return rows
