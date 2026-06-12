"""Cumulative project-history Markdown report (Phase C).

Unlike the main report (a snapshot of current rings) and Try This Week (only
the latest scan's changes), this report accumulates: every project's full
timeline since it first appeared on the radar. It grows day by day.
"""

from __future__ import annotations

from radar.storage.history_store import ProjectHistoryEvent, ProjectHistorySummary


def render_history_report(
    summaries: list[ProjectHistorySummary],
    events_by_project: dict[str, list[ProjectHistoryEvent]],
    title: str,
) -> str:
    """Render per-project timelines as Markdown, ordered by recency of change."""
    lines = [f"# {title}", ""]

    if not summaries:
        lines.append("No history recorded yet.")
        return "\n".join(lines) + "\n"

    ordered = sorted(summaries, key=lambda s: s.last_change_at, reverse=True)
    for summary in ordered:
        lines.extend(_project_lines(summary, events_by_project.get(summary.project, [])))
    return "\n".join(lines).rstrip() + "\n"


def _project_lines(
    summary: ProjectHistorySummary,
    events: list[ProjectHistoryEvent],
) -> list[str]:
    first = _date(summary.first_seen)
    lines = [
        f"## {summary.project}",
        "",
        (
            f"- **Category:** {summary.category.value}  "
            f"·  **Now:** `{summary.current_ring.value}`  "
            f"·  **On radar since:** {first}  "
            f"·  **Changes:** {summary.change_count}"
        ),
        "",
        "| Date | Change | Ring |",
        "| --- | --- | --- |",
    ]
    for event in events:
        ring = event.ring.value
        if event.previous_ring is not None:
            ring = f"{event.previous_ring.value} → {event.ring.value}"
        lines.append(f"| {_date(event.observed_at)} | {event.change_type.value} | {ring} |")
    lines.append("")
    return lines


def _date(value) -> str:
    return value.date().isoformat()
