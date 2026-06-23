"""Movers summary: what moved this scan and what is trending."""

from __future__ import annotations

from radar.pipeline.delta import CardDelta, ChangeType
from radar.pipeline.momentum import Momentum


MAX_TRENDING = 3


def build_mover_lines(
    deltas: list[CardDelta],
    momentums: list[Momentum],
) -> list[str]:
    """Human-readable mover lines: ring changes first, then star trends."""
    lines: list[str] = []
    for delta in deltas:
        if delta.change_type == ChangeType.PROMOTED and delta.previous_ring:
            lines.append(
                f"{delta.project}: {delta.previous_ring.value} → "
                f"{delta.current_ring.value} (promoted)"
            )
        elif delta.change_type == ChangeType.DEMOTED and delta.previous_ring:
            lines.append(
                f"{delta.project}: {delta.previous_ring.value} → "
                f"{delta.current_ring.value} (demoted)"
            )
        elif delta.change_type == ChangeType.NEW:
            lines.append(f"{delta.project}: new on the radar ({delta.current_ring.value})")

    moved = {line.split(":", 1)[0] for line in lines}
    trending = sorted(
        (m for m in momentums if m.direction == "rising" and m.project not in moved),
        key=lambda m: m.star_growth_pct or 0.0,
        reverse=True,
    )
    for momentum in trending[:MAX_TRENDING]:
        # The note names the driving signal (stars / downloads / mentions); fall
        # back to a bare label if a rising momentum carried no note.
        detail = momentum.note or "trending across recent scans"
        lines.append(f"{momentum.project}: rising — {detail}")
    return lines
