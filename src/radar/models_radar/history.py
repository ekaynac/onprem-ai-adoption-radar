"""Model ring-change events + append-only JSONL log (mirror of history_log)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from radar.models import Ring
from radar.models_radar.entities import ModelEntry
from radar.storage.history_store import ChangeType


logger = logging.getLogger(__name__)

_RING_ORDER = {Ring.AVOID: 0, Ring.WATCH: 1, Ring.PILOT: 2, Ring.ADOPT: 3}


class ModelHistoryEvent(BaseModel):
    model_id: str
    family: str
    change_type: ChangeType
    ring: Ring
    previous_ring: Ring | None = None
    run_id: str
    observed_at: datetime
    reasons: list[str] = Field(default_factory=list)


def diff_model_rings(
    entries: list[ModelEntry],
    previous_rings: dict[str, Ring],
    run_id: str,
    observed_at: datetime,
) -> list[ModelHistoryEvent]:
    """Emit new/promoted/demoted events. Unchanged rings emit nothing."""
    events: list[ModelHistoryEvent] = []
    for entry in entries:
        if entry.ring is None:
            continue
        prev = previous_rings.get(entry.id)
        if prev is None:
            change = ChangeType.NEW
        elif _RING_ORDER[entry.ring] > _RING_ORDER[prev]:
            change = ChangeType.PROMOTED
        elif _RING_ORDER[entry.ring] < _RING_ORDER[prev]:
            change = ChangeType.DEMOTED
        else:
            continue
        events.append(ModelHistoryEvent(
            model_id=entry.id, family=entry.family, change_type=change,
            ring=entry.ring, previous_ring=prev, run_id=run_id, observed_at=observed_at,
            reasons=[f"{change.value} to {entry.ring.value}"],
        ))
    return events


def append_model_events(path: Path, events: list[ModelHistoryEvent]) -> None:
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e.model_dump(mode="json"), ensure_ascii=False) for e in events]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def load_model_events(path: Path) -> list[ModelHistoryEvent]:
    if not path.exists():
        return []
    events: list[ModelHistoryEvent] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                events.append(ModelHistoryEvent.model_validate_json(line))
            except ValueError as exc:
                logger.warning("Skipping corrupt model-history line %d in %s: %s",
                               line_no, path, exc)
    return events
