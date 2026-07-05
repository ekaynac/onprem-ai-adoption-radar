"""Append-only JSONL audit log of autopilot source promotions.

Every auto-add appends a row here; the file is committed by the autopilot
workflow (like the history logs) and read by the weekly digest for the
"added this week" section. Mirror of trending_observations_log.py.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict


logger = logging.getLogger(__name__)


class AutopilotEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    repo: str
    source_id: str
    category: str
    stars: int
    avg_velocity: float
    added_at: datetime


def append_autopilot(path: Path, entries: list[AutopilotEntry]) -> None:
    if not entries:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e.model_dump(mode="json"), ensure_ascii=False) for e in entries]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def load_autopilot(path: Path) -> list[AutopilotEntry]:
    if not path.exists():
        return []
    entries: list[AutopilotEntry] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                entries.append(AutopilotEntry.model_validate_json(line))
            except ValueError as exc:
                logger.warning("Skipping corrupt autopilot-log line %d in %s: %s",
                               line_no, path, exc)
    return entries
