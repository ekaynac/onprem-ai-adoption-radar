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

from radar.models import Category, DecisionCard, Ring
from radar.reports.comparison import ComparisonError, build_comparison
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

    def recommendations(
        self,
        rings: list[str] | None = None,
        detail: str = "compact",
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return decision cards, optionally filtered by ring, newest-value first.

        Cards are sorted by score (highest first) so the most actionable picks
        lead and ``limit`` returns the top N. ``detail`` controls payload size:
        ``"compact"`` (default) returns a lean, context-cheap projection for
        browsing; ``"full"`` returns the complete card (same shape as
        ``get_project`` minus history) for callers that need every field.
        Unknown ring names are ignored rather than raising.
        """
        wanted: set[str] | None = None
        if rings is not None:
            valid = {r.value for r in Ring}
            wanted = {r.lower() for r in rings} & valid

        cards = self._cards()
        if wanted is not None:
            cards = [c for c in cards if c.ring.value in wanted]
        cards = sorted(cards, key=lambda c: c.score, reverse=True)
        if limit is not None and limit >= 0:
            cards = cards[:limit]

        render = self._card_dict if detail == "full" else self._card_compact
        return [render(c) for c in cards]

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

    def compare(
        self,
        projects: list[str] | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        """Return a side-by-side comparison matrix as a plain dict.

        Selection errors (unknown project, too few projects, bad selector) are
        returned as ``{"error": ...}`` rather than raised, so an MCP caller gets
        a clean message instead of a transport fault.
        """
        cat: Category | None = None
        if category is not None:
            try:
                cat = Category(category)
            except ValueError:
                return {"error": f"Unknown category: {category}"}
        try:
            comparison = build_comparison(
                self._cards(), projects=projects, category=cat
            )
        except ComparisonError as exc:
            return {"error": str(exc)}
        return {
            "projects": comparison.projects,
            "rows": [
                {"label": row.label, "values": row.values} for row in comparison.rows
            ],
        }

    def sandbox_plan(self, project: str) -> dict[str, Any] | None:
        """Return a disposable trial plan for a project, or None if unknown."""
        from radar.reports.sandbox import build_sandbox_plan

        card = next((c for c in self._cards() if c.project == project), None)
        if card is None:
            return None
        plan = build_sandbox_plan(card)
        return {
            "project": plan.project,
            "strategy": plan.strategy,
            "steps": plan.steps,
            "teardown": plan.teardown,
            "cautions": plan.cautions,
        }

    @staticmethod
    def _backer_dict(card: DecisionCard) -> dict[str, str] | None:
        """Who backs the project (person / community / company), or None."""
        if card.backer is None:
            return None
        return {"name": card.backer.name, "type": card.backer.type.value}

    @staticmethod
    def _backer_str(card: DecisionCard) -> str | None:
        """Flat backer string for compact views — saves ~17 chars vs nested object."""
        if card.backer is None:
            return None
        return f"{card.backer.name} ({card.backer.type.value})"

    @staticmethod
    def _strip_summary_prefix(summary: str, project: str) -> str:
        """Remove the boilerplate '{project} repository snapshot. ' prefix."""
        for suffix in (" repository snapshot. ", " reference. "):
            prefix = project + suffix
            if summary.startswith(prefix):
                return summary[len(prefix):]
        return summary

    @staticmethod
    def _headline_note(card: DecisionCard) -> str | None:
        """One high-signal evidence line for compact views.

        Prefers a security advisory (decision-critical) over the first note.
        """
        if not card.evidence_notes:
            return None
        advisory = next(
            (n for n in card.evidence_notes if "advisory" in n.lower()), None
        )
        return advisory or card.evidence_notes[0]

    @classmethod
    def _card_compact(cls, card: DecisionCard) -> dict[str, Any]:
        """Lean, context-cheap card for browsing — drill into get_project for all."""
        out: dict[str, Any] = {
            "project": card.project,
            "category": card.category.value,
            "backer": cls._backer_str(card),
            "ring": card.ring.value,
            "score": card.score,
            "risk_level": card.risk_level,
            "trend": card.trend,
            "summary": cls._strip_summary_prefix(card.summary, card.project),
            "headline": cls._headline_note(card),
        }
        # Omit defaults — saves ~430 tokens across a full project list.
        if card.upgrade_risk != "none":
            out["upgrade_risk"] = card.upgrade_risk
        if card.pinned:
            out["pinned"] = True
        return out

    @classmethod
    def _card_dict(cls, card: DecisionCard) -> dict[str, Any]:
        return {
            "project": card.project,
            "category": card.category.value,
            # Who backs the project (person / community / company), so an agent
            # can weigh provenance, not just the ring.
            "backer": cls._backer_dict(card),
            "ring": card.ring.value,
            "score": card.score,
            "risk_level": card.risk_level,
            "summary": card.summary,
            "why_it_matters": card.why_it_matters,
            "on_prem_fit": card.on_prem_fit,
            # Observed-evidence context so agents see WHY, not just the ring.
            "trend": card.trend,
            "evidence_notes": card.evidence_notes,
            "upgrade_risk": card.upgrade_risk,
            "upgrade_risk_notes": card.upgrade_risk_notes,
            # Human decision context: a pinned ring overrides the computed one.
            "pinned": card.pinned,
            "pinned_reason": card.pinned_reason,
            "computed_ring": card.computed_ring.value if card.computed_ring else None,
            "risks": card.risks,
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
            "reasons": event.reasons,
        }
