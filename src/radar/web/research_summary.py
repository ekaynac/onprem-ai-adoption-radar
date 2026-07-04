"""Immutable display summary of the technique catalog (mirror of models_summary)."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from radar.research_radar.entities import TechniqueEntry


class TechniquesSummary(BaseModel):
    """Immutable, display-ready summary of the technique catalog."""

    model_config = ConfigDict(frozen=True)

    total: int = 0
    by_ring: dict[str, int] = Field(default_factory=dict)
    by_domain: dict[str, int] = Field(default_factory=dict)

    @property
    def has_techniques(self) -> bool:
        return self.total > 0

    @property
    def one_line(self) -> str:
        adopt = self.by_ring.get("adopt", 0)
        pilot = self.by_ring.get("pilot", 0)
        return f"Research: {self.total} techniques — {adopt} adopt · {pilot} pilot"


def summarize_techniques(entries: Iterable[TechniqueEntry]) -> TechniquesSummary:
    total = 0
    by_ring: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    for entry in entries:
        total += 1
        if entry.ring is not None:
            by_ring[entry.ring.value] = by_ring.get(entry.ring.value, 0) + 1
        by_domain[entry.domain.value] = by_domain.get(entry.domain.value, 0) + 1
    return TechniquesSummary(total=total, by_ring=by_ring, by_domain=by_domain)
