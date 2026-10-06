"""``data/pulse/items.jsonl``: the merged, windowed set of Pulse items.

Merging is pure (returns a new list); only ``save_items`` touches disk, and it
writes to a temp file first so a crash never leaves a half-written store.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from radar.pulse.items import PulseItem


logger = logging.getLogger(__name__)


def merge_items(
    existing: Iterable[PulseItem],
    incoming: Iterable[PulseItem],
    now: datetime,
    window_days: int,
) -> list[PulseItem]:
    """Fresh fields win; ``first_seen`` is kept from the earliest sighting."""
    merged: dict[str, PulseItem] = {item.id: item for item in existing}
    for item in incoming:
        previous = merged.get(item.id)
        if previous is not None:
            item = item.model_copy(update={
                "first_seen": min(previous.first_seen, item.first_seen),
                # A model-card summary is fetched once; re-observations of the
                # repo carry none, so keep the one already stored.
                "summary": item.summary or previous.summary,
            })
        merged[item.id] = item
    cutoff = now - timedelta(days=window_days)
    kept = [item for item in merged.values() if (item.published_at or item.first_seen) >= cutoff]
    return sorted(kept, key=lambda i: (i.lane.value, i.key))


def load_items(path: Path) -> list[PulseItem]:
    if not path.exists():
        return []
    items: list[PulseItem] = []
    with path.open(encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            try:
                items.append(PulseItem.model_validate_json(raw))
            except ValidationError as exc:
                logger.warning("Skipping corrupt pulse item line %d in %s: %s", line_no, path, exc)
    return items


def save_items(path: Path, items: Iterable[PulseItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(item.model_dump_json() + "\n")
    os.replace(tmp, path)
