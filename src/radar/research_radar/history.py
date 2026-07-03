"""Technique ring-change events + append-only JSONL log (mirror of models_radar)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from radar.models import Ring
from radar.research_radar.entities import TechniqueDomain, TechniqueEntry
from radar.storage.history_store import ChangeType


logger = logging.getLogger(__name__)

_RING_ORDER = {Ring.AVOID: 0, Ring.WATCH: 1, Ring.PILOT: 2, Ring.ADOPT: 3}


class TechniqueHistoryEvent(BaseModel):
    technique_id: str
    domain: TechniqueDomain
    change_type: ChangeType
    ring: Ring
    previous_ring: Ring | None = None
    run_id: str
    observed_at: datetime
    reasons: list[str] = Field(default_factory=list)


def diff_technique_rings(
    entries: list[TechniqueEntry],
    previous_rings: dict[str, Ring],
    run_id: str,
    observed_at: datetime,
) -> list[TechniqueHistoryEvent]:
    """Emit new/promoted/demoted events. Unchanged rings emit nothing."""
    events: list[TechniqueHistoryEvent] = []
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
        events.append(TechniqueHistoryEvent(
            technique_id=entry.id, domain=entry.domain, change_type=change,
            ring=entry.ring, previous_ring=prev, run_id=run_id, observed_at=observed_at,
            reasons=[f"{change.value} to {entry.ring.value}"],
        ))
    return events


def append_technique_events(path: Path, events: list[TechniqueHistoryEvent]) -> None:
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e.model_dump(mode="json"), ensure_ascii=False) for e in events]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def load_technique_events(path: Path) -> list[TechniqueHistoryEvent]:
    if not path.exists():
        return []
    events: list[TechniqueHistoryEvent] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                events.append(TechniqueHistoryEvent.model_validate_json(line))
            except ValueError as exc:
                logger.warning("Skipping corrupt technique-history line %d in %s: %s",
                               line_no, path, exc)
    return events
