"""Render technique movers + report sections (mirror of models_radar/reports.py)."""

from __future__ import annotations

from radar.research_radar.entities import TechniqueEntry
from radar.research_radar.history import TechniqueHistoryEvent
from radar.research_radar.momentum import MomentumSignal
from radar.storage.history_store import ChangeType


MAX_TRENDING = 3


def build_technique_mover_lines(
    events: list[TechniqueHistoryEvent], momentums: list[MomentumSignal],
) -> list[str]:
    """Ring changes first, then up to MAX_TRENDING rising techniques not already shown."""
    lines: list[str] = []
    moved: set[str] = set()
    for ev in events:
        prev = ev.previous_ring.value if ev.previous_ring else "?"
        if ev.change_type == ChangeType.PROMOTED:
            lines.append(f"{ev.technique_id}: {prev} → {ev.ring.value} (promoted)")
            moved.add(ev.technique_id)
        elif ev.change_type == ChangeType.DEMOTED:
            lines.append(f"{ev.technique_id}: {prev} → {ev.ring.value} (demoted)")
            moved.add(ev.technique_id)
        elif ev.change_type == ChangeType.NEW:
            lines.append(f"{ev.technique_id}: new on the radar ({ev.ring.value})")
            moved.add(ev.technique_id)
    rising = sorted(
        (m for m in momentums if m.direction == "rising" and m.technique_id not in moved),
        key=lambda m: m.citation_growth_pct or 0.0, reverse=True,
    )
    for momentum in rising[:MAX_TRENDING]:
        pct = (f" citations {momentum.citation_growth_pct:+.1f}%"
               if momentum.citation_growth_pct is not None else "")
        lines.append(f"{momentum.technique_id}: rising —{pct} {momentum.note}".rstrip())
    return lines


def render_technique_report(
    entries: list[TechniqueEntry], mover_lines: list[str], title: str,
) -> str:
    out = [f"# {title}", ""]
    if mover_lines:
        out.append("## Movers")
        out += [f"- {line}" for line in mover_lines]
        out.append("")
    out.append("## Techniques")
    for entry in sorted(entries, key=lambda e: (e.domain.value, e.id)):
        ring = entry.ring.value if entry.ring else "-"
        impls = len(entry.resolved_implementations)
        citations = entry.citation_count if entry.citation_count is not None else "?"
        out.append(
            f"- **{entry.name}** ({entry.domain.value}) · `{ring}` · "
            f"{impls} impl(s) · {citations} citations"
        )
    out.append("")
    return "\n".join(out)
