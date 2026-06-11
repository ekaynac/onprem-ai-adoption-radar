"""JSON export renderer."""

from __future__ import annotations

import json

from radar.models import DecisionCard


def cards_to_json(cards: list[DecisionCard]) -> str:
    """Serialize cards to pretty JSON."""
    payload = [card.model_dump(mode="json") for card in cards]
    return json.dumps(payload, indent=2, ensure_ascii=False)
