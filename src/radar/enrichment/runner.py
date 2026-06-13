"""Run the enabled enrichers over a scan's projects and merge the results.

Enrichment is additive observation: every failure degrades to "no data" with
a warning, the input metrics dict is never mutated, and disabling all
enrichers reproduces the unenriched pipeline exactly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from radar.enrichment.downloads import fetch_weekly_downloads
from radar.enrichment.hackernews import fetch_hn_mentions
from radar.enrichment.osv import fetch_recent_advisories
from radar.models import Advisory, EnrichmentConfig, PackageRef, SourceConfig
from radar.storage.metrics_store import ProjectMetrics


logger = logging.getLogger(__name__)

_SEVERITY_ORDER = ["CRITICAL", "HIGH", "MODERATE", "MEDIUM", "LOW", "UNKNOWN"]


@dataclass(frozen=True)
class EnrichmentResult:
    """Enriched copies of the metrics rows plus per-project advisories."""

    metrics: dict[str, ProjectMetrics]
    advisories: dict[str, list[Advisory]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


async def run_enrichment(
    config: EnrichmentConfig,
    sources: list[SourceConfig],
    metrics: dict[str, ProjectMetrics],
    since: datetime,
    now: datetime,
    client: Any,
) -> EnrichmentResult:
    """Enrich each project's metrics row; returns new objects, never mutates."""
    packages = _packages_by_project(sources)
    advisories: dict[str, list[Advisory]] = {}
    warnings: list[str] = []
    enriched: dict[str, ProjectMetrics] = {}

    for project, row in metrics.items():
        updates: dict[str, Any] = {}
        package = packages.get(project)

        if config.osv and package is not None:
            found = await _safe(
                fetch_recent_advisories(package, client, now=now, window_days=config.advisory_window_days),
                f"osv:{project}",
                warnings,
            )
            if found:
                advisories[project] = found
                updates["advisories_open"] = len(found)
                updates["advisories_max_severity"] = _max_severity(found)

        if config.hackernews:
            mentions = await _safe(
                fetch_hn_mentions(project, client, since=since),
                f"hackernews:{project}",
                warnings,
            )
            if mentions is not None:
                updates["hn_mentions"] = mentions

        if config.downloads and package is not None:
            downloads = await _safe(
                fetch_weekly_downloads(package, client),
                f"downloads:{project}",
                warnings,
            )
            if downloads is not None:
                updates["downloads_weekly"] = downloads

        enriched[project] = row.model_copy(update=updates) if updates else row

    return EnrichmentResult(metrics=enriched, advisories=advisories, warnings=warnings)


def _packages_by_project(sources: list[SourceConfig]) -> dict[str, PackageRef]:
    return {
        source.project: source.package
        for source in sources
        if source.enabled and source.package is not None
    }


def _max_severity(advisories: list[Advisory]) -> str:
    severities = {a.severity.upper() for a in advisories}
    for level in _SEVERITY_ORDER:
        if level in severities:
            return level
    return "UNKNOWN"


async def _safe(coro: Any, label: str, warnings: list[str]) -> Any:
    try:
        return await coro
    except Exception as exc:
        message = f"enrichment {label} failed: {exc}"
        logger.warning(message)
        warnings.append(message)
        return None
