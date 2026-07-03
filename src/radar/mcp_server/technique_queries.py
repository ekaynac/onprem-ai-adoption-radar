"""Query service over persisted research (technique) runs — mirror of model_queries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from radar.research_radar.entities import TechniqueEntry
from radar.research_radar.history import load_technique_events
from radar.research_radar.pipeline import momentum_for
from radar.storage.run_store import RunStore


def _latest_technique_cards(root: Path) -> list[dict[str, Any]]:
    """Raw technique_cards.json dicts from the latest kind==research run; [] if none."""
    run_store = RunStore(Path(root) / "data" / "runs")
    for run_id in reversed(run_store.list_runs()):
        if run_store.read_meta(run_id).get("kind") == "research":
            path = run_store._run_dir(run_id) / "technique_cards.json"
            return json.loads(path.read_text(encoding="utf-8"))
    return []


class TechniqueQueryService:
    """Read-only technique queries for MCP tools (and the web/CLI loaders)."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.db_path = self.root / "data" / "radar.db"
        self.history_path = self.root / "data" / "technique-history.jsonl"

    def _entries(self) -> list[TechniqueEntry]:
        return [TechniqueEntry.model_validate(c) for c in _latest_technique_cards(self.root)]

    def list_techniques(
        self,
        ring: str | None = None,
        domain: str | None = None,
        category: str | None = None,
        detail: str = "compact",
    ) -> list[dict[str, Any]]:
        entries = self._entries()
        if ring:
            entries = [e for e in entries if e.ring and e.ring.value == ring.lower()]
        if domain:
            entries = [e for e in entries if e.domain.value == domain.lower()]
        if category:
            entries = [e for e in entries if e.category.value == category.lower()]
        if detail == "full":
            return [e.model_dump(mode="json") for e in entries]
        return [self._compact(e) for e in entries]

    def get_technique(self, technique_id: str) -> dict[str, Any] | None:
        entry = next((e for e in self._entries() if e.id == technique_id), None)
        if entry is None:
            return None
        payload = entry.model_dump(mode="json")
        payload["history"] = [
            ev.model_dump(mode="json")
            for ev in load_technique_events(self.history_path)
            if ev.technique_id == technique_id
        ]
        momentum = momentum_for([entry], self.db_path)[entry.id]
        payload["momentum"] = {
            "direction": momentum.direction, "score": momentum.score, "note": momentum.note,
        }
        return payload

    def technique_movers(self) -> list[dict[str, Any]]:
        events = load_technique_events(self.history_path)
        recent = sorted(events, key=lambda e: e.observed_at, reverse=True)[:10]
        return [{
            "technique_id": ev.technique_id,
            "change": ev.change_type.value,
            "ring": ev.ring.value,
            "previous_ring": ev.previous_ring.value if ev.previous_ring else None,
            "observed_at": ev.observed_at.isoformat(),
        } for ev in recent]

    @staticmethod
    def _compact(entry: TechniqueEntry) -> dict[str, Any]:
        return {
            "id": entry.id,
            "name": entry.name,
            "domain": entry.domain.value,
            "category": entry.category.value,
            "ring": entry.ring.value if entry.ring else None,
            "score": entry.score,
            "citation_count": entry.citation_count,
            "implementations": len(entry.resolved_implementations),
        }
