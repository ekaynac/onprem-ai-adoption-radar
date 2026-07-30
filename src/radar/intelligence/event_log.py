"""Idempotent canonical-JSONL mirror for public intelligence events."""

from __future__ import annotations

import json
from pathlib import Path

from radar.intelligence.events import IntelligenceEvent


class EventLog:
    def __init__(self, path: Path):
        self.path = path

    def append(self, event: IntelligenceEvent) -> bool:
        existing = {item.id for item in self.read()}
        if event.id in existing:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    event.model_dump(mode="json"),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
        return True

    def read(self) -> list[IntelligenceEvent]:
        if not self.path.exists():
            return []
        return [
            IntelligenceEvent.model_validate_json(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
