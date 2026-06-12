"""Transport-agnostic read queries over persisted radar state.

This wraps the existing decision-card and history stores. It never re-runs a
scan — it answers questions about the latest persisted results, so an agent can
ask "what should I try this week?" cheaply and deterministically. The MCP server
is a thin adapter over this service; keeping the logic here makes it testable
without any MCP transport.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from radar.models import DecisionCard, Ring
from radar.storage.database import RadarDatabase
from radar.storage.history_store import HistoryStore, ProjectHistoryEvent

# Rings that answer "what should I try this week?".
TRY_THIS_WEEK_RINGS = ("adopt", "pilot")


class RadarQueryService:
    """Read-only queries over the radar's persisted state."""

    def __init__(self, root: Path):
        self.root = Path(root)
        db_path = self.root / "data" / "radar.db"
        self.database = RadarDatabase(db_path)
        self.history = HistoryStore(db_path)

    def _cards(self) -> list[DecisionCard]:
        self.database.initialize()
        return self.database.list_cards()

    def recommendations(self, rings: list[str] | None = None) -> list[dict[str, Any]]:
        """Return decision cards as plain dicts, optionally filtered by ring.

        Unknown ring names are ignored rather than raising, so a caller passing
        a typo simply gets no matches for it.
        """
        wanted: set[str] | None = None
        if rings is not None:
            valid = {r.value for r in Ring}
            wanted = {r.lower() for r in rings} & valid

        cards = self._cards()
        if wanted is not None:
            cards = [c for c in cards if c.ring.value in wanted]
        return [self._card_dict(c) for c in cards]

    def list_projects(self) -> list[dict[str, Any]]:
        """Return a compact list of tracked projects with current ring."""
        return [
            {
                "project": c.project,
                "category": c.category.value,
                "ring": c.ring.value,
            }
            for c in self._cards()
        ]

    def get_project(self, project: str) -> dict[str, Any] | None:
        """Return a project's current card plus its observation history."""
        card = next((c for c in self._cards() if c.project == project), None)
        if card is None:
            return None
        self.history.initialize()
        events = self.history.history_for(project)
        detail = self._card_dict(card)
        detail["history"] = [self._event_dict(e) for e in events]
        return detail

    @staticmethod
    def _card_dict(card: DecisionCard) -> dict[str, Any]:
        return {
            "project": card.project,
            "category": card.category.value,
            "ring": card.ring.value,
            "risk_level": card.risk_level,
            "summary": card.summary,
            "why_it_matters": card.why_it_matters,
            "on_prem_fit": card.on_prem_fit,
            "try_next": card.try_next,
            "evidence": card.evidence,
            "tags": card.tags,
        }

    @staticmethod
    def _event_dict(event: ProjectHistoryEvent) -> dict[str, Any]:
        return {
            "change_type": event.change_type.value,
            "ring": event.ring.value,
            "previous_ring": event.previous_ring.value if event.previous_ring else None,
            "observed_at": event.observed_at.date().isoformat(),
            "run_id": event.run_id,
            "reasons": event.reasons,
        }
