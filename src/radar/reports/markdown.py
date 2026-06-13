"""Markdown report renderer."""

from __future__ import annotations

import re
from collections import defaultdict

from radar.models import DecisionCard, Ring


def render_markdown_report(cards: list[DecisionCard], title: str) -> str:
    """Render decision cards as a decision-oriented Markdown report."""
    lines = [f"# {_clean_inline(title)}", ""]
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
            lines.extend(_card_lines(card))
        lines.append("")
    return lines


def _card_lines(card: DecisionCard) -> list[str]:
    lines = [
        f"#### {_clean_inline(card.project)}",
        "",
        f"- **Decision:** `{card.ring.value}` (risk: `{card.risk_level}`)",
    ]
    lines.extend(_field("What changed", card.what_changed or [_clean_inline(card.summary)]))
    if card.evidence_notes:
        lines.extend(_field("Observed", card.evidence_notes))
    if card.upgrade_risk != "none":
        lines.extend(
            _field(f"Upgrade risk ({card.upgrade_risk})", card.upgrade_risk_notes)
        )
    lines.extend(_field("Why it matters", card.why_it_matters or card.summary))
    lines.extend(_field("On-prem fit", card.on_prem_fit or card.workflow_fit.get("enterprise_onprem", "unknown")))
    lines.extend(_field("Risks", card.risks or card.risk_reasons))
    lines.extend(_field("Try next", card.try_next or card.try_this_week))
    lines.extend(_field("Evidence", card.evidence or ["No evidence link recorded."]))
    return lines


def _field(label: str, value: str | list[str]) -> list[str]:
    if isinstance(value, str):
        cleaned = _clean_inline(value)
        return [f"- **{label}:** {cleaned}" if cleaned else f"- **{label}:** Not recorded."]
    if not value:
        return [f"- **{label}:** Not recorded."]
    lines = [f"- **{label}:**"]
    for item in value[:6]:
        lines.append(f"  - {_clean_inline(str(item))}")
    return lines


def _clean_inline(text: str) -> str:
    """Keep upstream Markdown from changing report hierarchy or producing giant blobs."""
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"^[>*`_\s]+", "", text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= 500:
        return text
    return text[:499].rstrip() + "…"
