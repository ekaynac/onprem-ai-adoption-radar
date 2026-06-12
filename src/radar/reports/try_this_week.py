"""Render the separate "Try This Week" delta report.

Unlike the full cumulative report, this artifact contains ONLY what changed
since the previous scan: new projects, ring promotions/demotions, and projects
with new release highlights.
"""

from __future__ import annotations

import re

from radar.pipeline.delta import CardDelta, ChangeType


_SECTIONS: list[tuple[ChangeType, str]] = [
    (ChangeType.NEW, "New on the radar"),
    (ChangeType.PROMOTED, "Promoted"),
    (ChangeType.UPDATED, "Updated"),
    (ChangeType.DEMOTED, "Demoted"),
]


def render_try_this_week_report(deltas: list[CardDelta], title: str) -> str:
    """Render changed projects grouped by change type as Markdown."""
    lines = [f"# {_clean_inline(title)}", ""]

    if not deltas:
        lines.extend(["No changes since the last scan.", ""])
        return "\n".join(lines).rstrip() + "\n"

    for change_type, heading in _SECTIONS:
        group = [d for d in deltas if d.change_type is change_type]
        if not group:
            continue
        lines.extend([f"## {heading}", ""])
        for delta in group:
            lines.extend(_delta_lines(delta))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _delta_lines(delta: CardDelta) -> list[str]:
    ring = delta.current_ring.value
    risk = delta.card.risk_level
    lines = [
        f"### {_clean_inline(delta.project)}",
        "",
        f"- **Category:** `{delta.category.value}`",
        f"- **Decision:** `{ring}` (risk: `{risk}`)",
    ]
    if delta.reasons:
        lines.append("- **Why now:**")
        for reason in delta.reasons[:6]:
            lines.append(f"  - {_clean_inline(reason)}")
    if delta.card.evidence:
        lines.append("- **Evidence:**")
        for link in delta.card.evidence[:6]:
            lines.append(f"  - {_clean_inline(str(link))}")
    lines.append("")
    return lines


def _clean_inline(text: str) -> str:
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"^[>*`_\s]+", "", text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= 500:
        return text
    return text[:499].rstrip() + "…"
