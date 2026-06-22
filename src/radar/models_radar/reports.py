"""Render model movers + report sections from model history/momentum."""

from __future__ import annotations

from radar.models_radar.history import ModelHistoryEvent
from radar.models_radar.momentum import ModelMomentum
from radar.storage.history_store import ChangeType


MAX_TRENDING = 3


def build_model_mover_lines(
    events: list[ModelHistoryEvent], momentums: list[ModelMomentum],
) -> list[str]:
    """Ring changes first, then up to MAX_TRENDING rising models not already shown."""
    lines: list[str] = []
    moved: set[str] = set()
    for ev in events:
        if ev.change_type == ChangeType.PROMOTED:
            lines.append(f"{ev.model_id}: {ev.previous_ring.value if ev.previous_ring else '?'} "
                         f"→ {ev.ring.value} (promoted)")
            moved.add(ev.model_id)
        elif ev.change_type == ChangeType.DEMOTED:
            lines.append(f"{ev.model_id}: {ev.previous_ring.value if ev.previous_ring else '?'} "
                         f"→ {ev.ring.value} (demoted)")
            moved.add(ev.model_id)
        elif ev.change_type == ChangeType.NEW:
            lines.append(f"{ev.model_id}: new on the radar ({ev.ring.value})")
            moved.add(ev.model_id)
    rising = sorted(
        (m for m in momentums if m.direction == "rising" and m.model_id not in moved),
        key=lambda m: m.downloads_growth_pct or 0.0, reverse=True,
    )
    for m in rising[:MAX_TRENDING]:
        pct = f" downloads {m.downloads_growth_pct:+.1f}%" if m.downloads_growth_pct is not None else ""
        lines.append(f"{m.model_id}: rising —{pct} across recent scans".replace("— ", "— "))
    return lines
