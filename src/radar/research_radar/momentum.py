"""Technique momentum: 1-5 score + direction from metric history.

Velocity only compares same-source citation counts (S2 vs OpenAlex counts
differ wildly for the same paper), while implementation deltas compare
against the most recent row of any source.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from radar.storage.technique_metrics_store import TechniqueMetrics


CITATION_RISING_PCT = 10.0


class MomentumSignal(BaseModel):
    model_config = ConfigDict(frozen=True)

    technique_id: str
    score: int  # 1-5, feeds TechniqueScore.momentum
    direction: str  # rising | falling | steady
    citation_growth_pct: float | None = None
    note: str = ""


def momentum_signal(
    technique_id: str,
    previous_rows: list[TechniqueMetrics],
    citation_count: int | None,
    citation_source: str | None,
    impl_count: int,
) -> MomentumSignal:
    """Rows are oldest-first and exclude the current scan (compute before persist)."""
    growth = _citation_growth_pct(previous_rows, citation_count, citation_source)
    impl_delta = _impl_delta(previous_rows, impl_count)
    if impl_delta is not None and impl_delta > 0:
        return MomentumSignal(
            technique_id=technique_id, score=5, direction="rising",
            citation_growth_pct=growth,
            note=f"+{impl_delta} tracked implementation(s) since last scan.",
        )
    if growth is not None and growth < 0:
        lost = impl_delta is not None and impl_delta < 0
        return MomentumSignal(
            technique_id=technique_id, score=1 if lost else 2, direction="falling",
            citation_growth_pct=growth,
            note="Citations falling" + (" and an implementation dropped." if lost else "."),
        )
    if growth is not None and growth >= CITATION_RISING_PCT:
        return MomentumSignal(
            technique_id=technique_id, score=4, direction="rising",
            citation_growth_pct=growth,
            note=f"Citations {growth:+.1f}% since last comparable scan.",
        )
    return MomentumSignal(technique_id=technique_id, score=3, direction="steady",
                          citation_growth_pct=growth)


def _citation_growth_pct(
    rows: list[TechniqueMetrics], current: int | None, source: str | None,
) -> float | None:
    if current is None or source is None:
        return None
    for row in reversed(rows):  # most recent same-source row wins
        if row.citation_source != source:
            continue
        if not row.citation_count:  # zero/None baseline: pct growth is undefined
            return None
        return round((current - row.citation_count) / row.citation_count * 100, 1)
    return None


def _impl_delta(rows: list[TechniqueMetrics], current: int) -> int | None:
    for row in reversed(rows):
        if row.resolved_impls is not None:
            return current - row.resolved_impls
    return None
