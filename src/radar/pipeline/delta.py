"""Cross-run delta computation.

Compares the decision cards from the previous scan against the current scan and
classifies how each project changed. This powers the separate "Try This Week"
delta report, which surfaces only what is new or changed since the last scan.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from radar.models import Category, DecisionCard, Ring


# Higher rank == closer to "adopt now". Used to detect promotion vs demotion.
_RING_RANK: dict[Ring, int] = {
    Ring.AVOID: 0,
    Ring.WATCH: 1,
    Ring.PILOT: 2,
    Ring.ADOPT: 3,
}

_SNAPSHOT_PREFIX = "Repo snapshot:"


class ChangeType(str, Enum):
    """How a project changed between two scans."""

    NEW = "new"
    PROMOTED = "promoted"
    DEMOTED = "demoted"
    UPDATED = "updated"


# Stable display/sort order: new projects first, then promotions, then the rest.
_CHANGE_ORDER: dict[ChangeType, int] = {
    ChangeType.NEW: 0,
    ChangeType.PROMOTED: 1,
    ChangeType.UPDATED: 2,
    ChangeType.DEMOTED: 3,
}


class CardDelta(BaseModel):
    """A single project's change between the previous and current scan."""

    project: str
    category: Category
    change_type: ChangeType
    current_ring: Ring
    previous_ring: Ring | None = None
    reasons: list[str] = Field(default_factory=list)
    card: DecisionCard


def compute_deltas(
    previous: list[DecisionCard],
    current: list[DecisionCard],
) -> list[CardDelta]:
    """Return one CardDelta per *changed* current project.

    Unchanged projects (and pure snapshot-metric drift) are omitted so the
    delta report only contains genuinely new or changed signals. Inputs are
    never mutated.
    """
    previous_by_project = {card.project: card for card in previous}

    deltas: list[CardDelta] = []
    for card in current:
        prior = previous_by_project.get(card.project)
        delta = _classify(prior, card)
        if delta is not None:
            deltas.append(delta)

    return sorted(
        deltas,
        key=lambda d: (_CHANGE_ORDER[d.change_type], d.project.lower()),
    )


def _classify(prior: DecisionCard | None, card: DecisionCard) -> CardDelta | None:
    """Classify a single project's change, or None if unchanged."""
    if prior is None:
        return CardDelta(
            project=card.project,
            category=card.category,
            change_type=ChangeType.NEW,
            current_ring=card.ring,
            previous_ring=None,
            reasons=_with_highlights(["New on the radar."], prior, card),
            card=card,
        )

    prior_rank = _RING_RANK[prior.ring]
    current_rank = _RING_RANK[card.ring]
    if current_rank > prior_rank:
        return CardDelta(
            project=card.project,
            category=card.category,
            change_type=ChangeType.PROMOTED,
            current_ring=card.ring,
            previous_ring=prior.ring,
            reasons=_with_highlights(
                [f"Ring moved {prior.ring.value} -> {card.ring.value}."], prior, card
            ),
            card=card,
        )
    if current_rank < prior_rank:
        return CardDelta(
            project=card.project,
            category=card.category,
            change_type=ChangeType.DEMOTED,
            current_ring=card.ring,
            previous_ring=prior.ring,
            reasons=_with_highlights(
                [f"Ring moved {prior.ring.value} -> {card.ring.value}."], prior, card
            ),
            card=card,
        )

    new_highlights = _new_highlights(prior, card)
    if new_highlights:
        return CardDelta(
            project=card.project,
            category=card.category,
            change_type=ChangeType.UPDATED,
            current_ring=card.ring,
            previous_ring=prior.ring,
            reasons=new_highlights,
            card=card,
        )

    return None


def _meaningful_highlights(card: DecisionCard) -> list[str]:
    """Highlights excluding noisy per-scan repo snapshot metric lines."""
    return [
        change
        for change in card.what_changed
        if not change.startswith(_SNAPSHOT_PREFIX)
    ]


def _new_highlights(prior: DecisionCard, card: DecisionCard) -> list[str]:
    """Meaningful highlights present now but not in the previous scan."""
    previous_seen = set(_meaningful_highlights(prior))
    return [h for h in _meaningful_highlights(card) if h not in previous_seen]


def _with_highlights(
    base: list[str], prior: DecisionCard | None, card: DecisionCard
) -> list[str]:
    """Append any new meaningful highlights to a base reason list."""
    extra = _meaningful_highlights(card) if prior is None else _new_highlights(prior, card)
    return base + extra
