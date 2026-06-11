"""Markdown report renderer."""

from __future__ import annotations

from collections import defaultdict

from radar.models import DecisionCard, Ring


def render_markdown_report(cards: list[DecisionCard], title: str) -> str:
    """Render decision cards as a decision-oriented Markdown report."""
    lines = [f"# {title}", ""]
    lines.extend(
        _section("Try This Week", [c for c in cards if c.ring in {Ring.ADOPT, Ring.PILOT}])
    )
    lines.extend(_section("Watch", [c for c in cards if c.ring == Ring.WATCH]))
    lines.extend(_section("Avoid", [c for c in cards if c.ring == Ring.AVOID]))
    return "\n".join(lines).rstrip() + "\n"


def _section(title: str, cards: list[DecisionCard]) -> list[str]:
    lines = [f"## {title}", ""]
    if not cards:
        lines.extend(["No items in this section.", ""])
        return lines

    grouped: dict[str, list[DecisionCard]] = defaultdict(list)
    for card in cards:
        grouped[card.category.value].append(card)

    for category, category_cards in grouped.items():
        lines.extend([f"### {category}", ""])
        for card in category_cards:
            evidence = (
                ", ".join(card.evidence) if card.evidence else "No evidence link recorded"
            )
            risks = (
                " ".join(card.risk_reasons)
                if card.risk_reasons
                else "No risk notes recorded."
            )
            lines.extend(
                [
                    f"- **{card.project}** (`{card.ring.value}`, risk: `{card.risk_level}`)",
                    f"  - {card.summary}",
                    f"  - Risk: {risks}",
                    f"  - Evidence: {evidence}",
                ]
            )
        lines.append("")
    return lines
