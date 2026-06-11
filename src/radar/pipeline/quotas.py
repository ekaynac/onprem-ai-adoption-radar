"""Balanced report selection."""

from __future__ import annotations

from collections import defaultdict

from radar.models import Category, DecisionCard


def apply_category_quotas(
    cards: list[DecisionCard],
    quotas: dict[Category, int],
) -> list[DecisionCard]:
    """Limit cards per category while preserving input order."""
    counts: dict[Category, int] = defaultdict(int)
    selected: list[DecisionCard] = []
    for card in cards:
        limit = quotas.get(card.category)
        if limit is not None and counts[card.category] >= limit:
            continue
        selected.append(card)
        counts[card.category] += 1
    return selected
