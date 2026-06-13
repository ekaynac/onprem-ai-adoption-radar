"""Human decisions over the radar: pinned rings and trial outcomes.

Stored in a portable ``data/overrides.yaml`` (like the history log, it can be
committed or synced). A pinned ring wins on the card — the radar's computed
ring is preserved alongside it and any disagreement is surfaced as drift, so
the human decision and the data-driven decision stay visibly in tension
instead of silently diverging.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from radar.models import DecisionCard, Ring


TRIAL_OUTCOMES = {"adopted", "rejected", "inconclusive"}


class RingOverride(BaseModel):
    """A manually pinned ring for a project."""

    model_config = ConfigDict(extra="forbid")

    project: str
    ring: Ring
    reason: str
    set_at: datetime


class TrialRecord(BaseModel):
    """The outcome of actually trying a tool (the decision journal)."""

    model_config = ConfigDict(extra="forbid")

    project: str
    outcome: str
    notes: str = ""
    recorded_at: datetime

    @field_validator("outcome")
    @classmethod
    def validate_outcome(cls, value: str) -> str:
        if value not in TRIAL_OUTCOMES:
            raise ValueError(f"outcome must be one of {sorted(TRIAL_OUTCOMES)}")
        return value


class OverridesFile(BaseModel):
    """The full contents of data/overrides.yaml."""

    model_config = ConfigDict(extra="forbid")

    overrides: list[RingOverride] = Field(default_factory=list)
    trials: list[TrialRecord] = Field(default_factory=list)


class OverridesStore:
    """Load/update the portable overrides file."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> OverridesFile:
        """Parse the file; a missing file is an empty journal."""
        if not self.path.exists():
            return OverridesFile()
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        return OverridesFile.model_validate(raw)

    def set_override(self, override: RingOverride) -> None:
        """Pin a project's ring, replacing any existing pin for it."""
        current = self.load()
        kept = [o for o in current.overrides if o.project != override.project]
        self._save(current.model_copy(update={"overrides": [*kept, override]}))

    def clear_override(self, project: str) -> bool:
        """Remove a project's pin. Returns False when none existed."""
        current = self.load()
        kept = [o for o in current.overrides if o.project != project]
        if len(kept) == len(current.overrides):
            return False
        self._save(current.model_copy(update={"overrides": kept}))
        return True

    def add_trial(self, trial: TrialRecord) -> None:
        """Append a trial outcome to the journal."""
        current = self.load()
        self._save(current.model_copy(update={"trials": [*current.trials, trial]}))

    def _save(self, contents: OverridesFile) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            yaml.safe_dump(
                contents.model_dump(mode="json"), sort_keys=False, allow_unicode=True
            ),
            encoding="utf-8",
        )
        tmp.replace(self.path)


def apply_overrides(
    cards: list[DecisionCard],
    overrides: list[RingOverride],
) -> list[DecisionCard]:
    """Return new cards with pinned rings applied; never mutates the input."""
    by_project = {o.project: o for o in overrides}
    result: list[DecisionCard] = []
    for card in cards:
        override = by_project.get(card.project)
        if override is None:
            result.append(card)
            continue
        notes = list(card.evidence_notes)
        if override.ring != card.ring:
            notes.append(
                f"Drift: computed ring is {card.ring.value}, "
                f"pinned to {override.ring.value} ({override.reason})."
            )
        result.append(
            card.model_copy(
                update={
                    "ring": override.ring,
                    "computed_ring": card.ring,
                    "pinned": True,
                    "pinned_reason": override.reason,
                    "evidence_notes": notes,
                }
            )
        )
    return result
