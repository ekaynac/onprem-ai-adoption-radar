"""Immutable index-strip summary of the trending catalog (mirror of research_summary)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from radar.discovery.trending_entities import Lane, TrendingEntry


_TOP_N = 3


class TrendingSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    onprem_top: list[TrendingEntry] = Field(default_factory=list)
    onprem_count: int = 0
    broader_count: int = 0

    @property
    def has_trending(self) -> bool:
        return self.onprem_count > 0 or self.broader_count > 0

    @property
    def one_line(self) -> str:
        return (f"Trending: {self.onprem_count} on-prem candidates · "
                f"{self.broader_count} elsewhere in AI")


def summarize_trending(entries: list[TrendingEntry]) -> TrendingSummary:
    onprem = [e for e in entries if e.lane == Lane.ONPREM]
    broader = [e for e in entries if e.lane == Lane.BROADER]
    return TrendingSummary(
        onprem_top=onprem[:_TOP_N], onprem_count=len(onprem), broader_count=len(broader),
    )
