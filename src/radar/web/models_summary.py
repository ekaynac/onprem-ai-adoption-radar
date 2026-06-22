"""Immutable display summary of the model catalog (mirror of source_health)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from radar.models_radar.entities import ModelEntry


class ModelsSummary(BaseModel):
    """Immutable, display-ready summary of model catalog."""

    model_config = ConfigDict(frozen=True)

    total: int = 0
    by_ring: dict[str, int] = Field(default_factory=dict)
    by_tier: dict[str, int] = Field(default_factory=dict)

    @property
    def has_models(self) -> bool:
        return self.total > 0

    @property
    def one_line(self) -> str:
        if not self.total:
            return "Models: no models scanned yet."
        adopt = self.by_ring.get("adopt", 0)
        return f"Models: {self.total} tracked, {adopt} adopt-ready."


def summarize_models(entries: Iterable[ModelEntry]) -> ModelsSummary:
    """Build a ModelsSummary from model entries.

    Counts are grouped by ring and hardware tier. Entries with missing ring or tier
    are skipped from those dimensions (not added to the respective counter).
    """
    items = list(entries)
    by_ring = Counter(e.ring.value for e in items if e.ring)
    by_tier = Counter(e.hardware_tier.value for e in items if e.hardware_tier)
    return ModelsSummary(total=len(items), by_ring=dict(by_ring), by_tier=dict(by_tier))
