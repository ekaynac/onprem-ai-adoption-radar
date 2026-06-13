"""Evidence assembly: collected signals -> per-project metrics -> evidence.

Sits between collection and scoring. ``collect_project_metrics`` reduces a
scan's signals to one observed-metrics row per project; ``build_evidence``
compares that row with the previous scan's row to produce the immutable
``ProjectEvidence`` consumed by scoring; ``evidence_notes`` renders the
human-readable lines shown on cards and reports.
"""

from __future__ import annotations

from datetime import datetime

from radar.models import Advisory, ProjectEvidence, Signal
from radar.storage.metrics_store import ProjectMetrics


def collect_project_metrics(
    signals: list[Signal],
    run_id: str,
    observed_at: datetime,
) -> dict[str, ProjectMetrics]:
    """Reduce a scan's signals to one observed-metrics row per project."""
    metrics: dict[str, ProjectMetrics] = {}

    def row_for(project: str) -> ProjectMetrics:
        if project not in metrics:
            metrics[project] = ProjectMetrics(
                project=project, run_id=run_id, observed_at=observed_at
            )
        return metrics[project]

    for signal in signals:
        if signal.signal_type == "github_repo_snapshot":
            snapshot = signal.metadata
            current = row_for(signal.project)
            metrics[signal.project] = current.model_copy(
                update={
                    "stars": _opt_int(snapshot.get("stars")),
                    "forks": _opt_int(snapshot.get("forks")),
                    "open_issues": _opt_int(snapshot.get("open_issues")),
                    "license": snapshot.get("license") or None,
                    "pushed_at": snapshot.get("pushed_at") or None,
                }
            )
        elif signal.signal_type == "github_release":
            current = row_for(signal.project)
            metrics[signal.project] = current.model_copy(
                update={"releases_in_window": current.releases_in_window + 1}
            )
    return metrics


def build_evidence(
    current: ProjectMetrics | None,
    previous: ProjectMetrics | None,
    now: datetime,
    advisories: list[Advisory] | None = None,
) -> ProjectEvidence:
    """Compare current vs previous metrics into scoring-ready evidence."""
    if current is None:
        return ProjectEvidence(advisories=advisories or [])

    star_growth: int | None = None
    star_growth_pct: float | None = None
    if (
        previous is not None
        and current.stars is not None
        and previous.stars is not None
    ):
        star_growth = current.stars - previous.stars
        if previous.stars > 0:
            star_growth_pct = round(star_growth / previous.stars * 100, 1)

    license_changed_from: str | None = None
    if (
        previous is not None
        and current.license
        and previous.license
        and current.license != previous.license
    ):
        license_changed_from = previous.license

    days_since_push: int | None = None
    if current.pushed_at:
        try:
            pushed = datetime.fromisoformat(current.pushed_at.replace("Z", "+00:00"))
            days_since_push = max(0, (now - pushed).days)
        except ValueError:
            days_since_push = None

    return ProjectEvidence(
        star_growth=star_growth,
        star_growth_pct=star_growth_pct,
        releases_in_window=current.releases_in_window,
        days_since_push=days_since_push,
        advisories=advisories or [],
        downloads_weekly=current.downloads_weekly,
        hn_mentions=current.hn_mentions,
        license=current.license,
        license_changed_from=license_changed_from,
    )


def evidence_notes(evidence: ProjectEvidence) -> list[str]:
    """Render evidence as human-readable card/report lines. Empty evidence → []."""
    notes: list[str] = []
    if evidence.star_growth is not None:
        pct = f" ({evidence.star_growth_pct:+.1f}%)" if evidence.star_growth_pct is not None else ""
        notes.append(f"Stars {evidence.star_growth:+,}{pct} since last scan.")
    if evidence.releases_in_window:
        plural = "s" if evidence.releases_in_window != 1 else ""
        notes.append(f"{evidence.releases_in_window} release{plural} in the scan window.")
    for advisory in evidence.advisories:
        notes.append(
            f"Recent {advisory.severity} security advisory {advisory.id}"
            + (f": {advisory.summary}" if advisory.summary else ".")
        )
    if evidence.license_changed_from:
        notes.append(
            f"License changed: {evidence.license_changed_from} → {evidence.license or 'unknown'}."
        )
    if evidence.hn_mentions:
        notes.append(f"{evidence.hn_mentions} Hacker News mentions in the scan window.")
    if evidence.downloads_weekly is not None:
        notes.append(f"{evidence.downloads_weekly:,} weekly downloads.")
    return notes


def _opt_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None
