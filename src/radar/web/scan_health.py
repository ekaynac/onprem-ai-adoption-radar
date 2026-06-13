"""Summarize a scan's run-meta into a small 'scan health' view.

Collector/enrichment/firehose warnings are recorded in each run's ``meta.json``
(by the orchestrator) but were never surfaced. This pure helper turns that meta
into an immutable, display-ready summary for the dashboard, the static export,
and the ``radar scan`` CLI line. Defensive by design: external/handwritten meta
is never trusted, and the input dict is never mutated.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ScanHealth(BaseModel):
    """Immutable, display-ready summary of a scan's warnings."""

    model_config = ConfigDict(frozen=True)

    last_run_at: str | None = None
    profile: str | None = None
    notified: bool = False
    collector_warning_count: int = 0
    enrichment_warning_count: int = 0
    firehose_dropped_count: int = 0
    firehose_llm_recovered: int = 0
    collector_warnings: list[str] = Field(default_factory=list)
    enrichment_warnings: list[str] = Field(default_factory=list)
    firehose_dropped_sample: list[str] = Field(default_factory=list)

    @property
    def has_warnings(self) -> bool:
        return bool(
            self.collector_warning_count
            or self.enrichment_warning_count
            or self.firehose_dropped_count
        )

    @property
    def one_line(self) -> str:
        """Compact human summary for the CLI / template header."""
        if self.last_run_at is None:
            return "Scan health: no scans yet."
        parts: list[str] = []
        if self.collector_warning_count:
            parts.append(_plural(self.collector_warning_count, "collector warning"))
        if self.enrichment_warning_count:
            parts.append(_plural(self.enrichment_warning_count, "enrichment warning"))
        if self.firehose_dropped_count:
            parts.append(f"{self.firehose_dropped_count} firehose entries dropped")
        if not parts:
            return "Scan health: no warnings."
        return "Scan health: " + ", ".join(parts) + "."


def summarize_meta(meta: dict[str, Any]) -> ScanHealth:
    """Build a ScanHealth from a run's meta dict (never mutates ``meta``)."""
    collector = _str_list(meta.get("collector_warnings"))
    enrichment = _str_list(meta.get("enrichment_warnings"))
    sample = _str_list(meta.get("firehose_dropped_sample"))
    return ScanHealth(
        last_run_at=meta.get("updated_at") or meta.get("created_at"),
        profile=meta.get("profile") if isinstance(meta.get("profile"), str) else None,
        notified=bool(meta.get("notified", False)),
        collector_warning_count=len(collector),
        enrichment_warning_count=len(enrichment),
        firehose_dropped_count=_int(meta.get("firehose_dropped_count")),
        firehose_llm_recovered=_int(meta.get("firehose_llm_recovered")),
        collector_warnings=collector,
        enrichment_warnings=enrichment,
        firehose_dropped_sample=sample,
    )


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")
