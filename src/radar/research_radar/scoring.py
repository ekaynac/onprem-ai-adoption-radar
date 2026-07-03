"""Deterministic technique scoring + ring gate.

The two implementation dimensions are the closed loop: they read the rings
the radar's *own* tool and model scans produced, so research verdicts move
when tool verdicts move. No network anywhere in this module.
"""

from __future__ import annotations

from radar.models import Ring
from radar.research_radar.entities import (
    ImplKind,
    OnPremImpact,
    ResolvedImplementation,
    TechniqueEntry,
    TechniqueScore,
)
from radar.research_radar.momentum import MomentumSignal


CITATIONS_HIGH = 500
CITATIONS_MID = 100
CITATIONS_LOW = 25

_IMPACT_SCORE = {
    OnPremImpact.REDUCES_MEMORY: 5,
    OnPremImpact.REDUCES_LATENCY: 5,
    OnPremImpact.ENABLES_SCALE: 4,
    OnPremImpact.IMPROVES_SAFETY: 4,
    OnPremImpact.IMPROVES_QUALITY: 3,
}


def score_technique(entry: TechniqueEntry, momentum: MomentumSignal) -> TechniqueScore:
    impls = entry.resolved_implementations
    breadth = _breadth(len(impls))
    maturity = _maturity(impls)
    validation = _validation(entry)
    reproducibility = _reproducibility(entry)
    impact = _IMPACT_SCORE[entry.onprem_impact]
    average = round(
        (breadth + maturity + validation + reproducibility + momentum.score + impact) / 6, 2
    )
    return TechniqueScore(
        implementation_breadth=breadth, implementation_maturity=maturity,
        validation=validation, reproducibility=reproducibility,
        momentum=momentum.score, onprem_impact=impact, average=average,
    )


def technique_ring(score: TechniqueScore, resolved_count: int, superseded: bool = False) -> Ring:
    """Absolute gates. The WATCH caps come after AVOID on purpose: you cannot
    adopt what you cannot run on-prem — or what has a named successor — but
    AVOID stays reachable below both caps."""
    if score.average < 2.0:
        return Ring.AVOID
    if superseded or resolved_count == 0:
        return Ring.WATCH
    if score.average >= 4.0 and score.implementation_maturity >= 4:
        return Ring.ADOPT
    if score.average >= 3.0:
        return Ring.PILOT
    return Ring.WATCH


def _breadth(count: int) -> int:
    if count >= 5:
        return 5
    if count >= 3:
        return 4
    return count + 1  # 0→1, 1→2, 2→3


def _maturity(impls: list[ResolvedImplementation]) -> int:
    """Avoid-ring implementations count as unringed: not evidence of maturity."""
    rings = [i.ring for i in impls if i.ring is not None and i.ring != Ring.AVOID]
    adopts = sum(1 for r in rings if r == Ring.ADOPT)
    if adopts >= 2:
        return 5
    if adopts == 1:
        return 4
    if Ring.PILOT in rings:
        return 3
    if Ring.WATCH in rings:
        return 2
    return 1


def _validation(entry: TechniqueEntry) -> int:
    if entry.superseded_by is not None:
        return 1
    count = entry.citation_count
    if count is None:
        return 2  # unknown → neutral; the entry carries a "citations unknown" warning
    peer_reviewed = bool(entry.peer_reviewed)
    if peer_reviewed and count >= CITATIONS_HIGH:
        return 5
    if count >= CITATIONS_MID:
        return 4
    if count >= CITATIONS_LOW or peer_reviewed:
        return 3
    return 2


def _reproducibility(entry: TechniqueEntry) -> int:
    has_tool_impl = any(
        i.kind == ImplKind.TOOL for i in entry.resolved_implementations
    )
    if entry.open_code and has_tool_impl:
        return 5
    if entry.open_code:
        return 4
    if has_tool_impl:
        return 3
    return 1
