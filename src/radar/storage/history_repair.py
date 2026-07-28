"""One-off corrective repair for outage-polluted ring history.

The 2026-07-27 audit proved that scans which failed to reach most sources
were still scored, promoting the few network-free (manual) projects and
demoting them again the next healthy day. Those runs are identifiable from
per-source signal counts; this module appends `corrected` marker events that
neutralize their ring changes. The log stays append-only — nothing is ever
rewritten (spec D1).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from radar.pipeline.delta import ChangeType
from radar.storage.history_store import ProjectHistoryEvent


def outage_run_ids(
    db_path: Path,
    *,
    zero_fraction: float = 0.5,
    min_sources: int = 10,
) -> set[str]:
    """Runs where >= zero_fraction of recorded sources produced 0 signals.

    Runs with fewer than min_sources recorded rows are skipped — a tiny
    test/dev scan is not evidence of an outage. Works on legacy rows (status
    NULL) because the criterion needs only counts.
    """
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT run_id, COUNT(*), SUM(CASE WHEN signal_count = 0 THEN 1 ELSE 0 END) "
            "FROM source_health GROUP BY run_id"
        ).fetchall()
    return {
        run_id
        for run_id, total, zeros in rows
        if total >= min_sources and zeros / total >= zero_fraction
    }


def build_corrections(
    events: list[ProjectHistoryEvent],
    outage_runs: set[str],
    observed_at: datetime,
) -> list[ProjectHistoryEvent]:
    """Marker events neutralizing promoted/demoted artifacts from outage runs.

    Idempotent: (project, run) pairs already corrected in `events` are skipped,
    so re-running repair appends nothing.
    """
    already = {
        (e.project, e.corrects_run_id)
        for e in events
        if e.change_type == ChangeType.CORRECTED and e.corrects_run_id
    }
    corrections: list[ProjectHistoryEvent] = []
    for event in events:
        if event.run_id not in outage_runs:
            continue
        if event.change_type not in (ChangeType.PROMOTED, ChangeType.DEMOTED):
            continue
        if (event.project, event.run_id) in already:
            continue
        already.add((event.project, event.run_id))
        corrections.append(
            ProjectHistoryEvent(
                project=event.project,
                category=event.category,
                change_type=ChangeType.CORRECTED,
                ring=event.previous_ring or event.ring,
                previous_ring=event.ring,
                run_id=f"repair:{event.run_id}",
                observed_at=observed_at,
                reasons=[
                    "collection outage artifact; neutralizes "
                    f"{event.change_type.value} from {event.run_id} "
                    "(2026-07-27 hardening spec)"
                ],
                corrects_run_id=event.run_id,
            )
        )
    return corrections
