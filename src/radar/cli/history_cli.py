"""``radar history`` — project ring timeline (and outage repair)."""

from __future__ import annotations

from pathlib import Path

import typer

from radar.cli._shared import console


history_app = typer.Typer(help="Project ring timeline.", invoke_without_command=True)


@history_app.callback()
def history(
    ctx: typer.Context,
    project: str = typer.Option("", help="Limit to a single project (optional)."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Print the cumulative per-project observation history."""
    if ctx.invoked_subcommand is not None:
        return
    from radar.reports.history import render_history_report
    from radar.storage.history_store import HistoryStore

    store = HistoryStore(root / "data" / "radar.db")
    store.initialize()
    # all_summaries(), not summaries(): a project entirely corrected away
    # must still show its raw timeline here.
    summaries = store.all_summaries()
    if project:
        summaries = [s for s in summaries if s.project == project]
    events = {s.project: store.history_for(s.project) for s in summaries}
    console.print(render_history_report(summaries, events, "Adoption History"))


@history_app.command("repair")
def history_repair(
    root: Path = typer.Option(Path("."), help="Project root."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show corrections, write nothing."),
) -> None:
    """Neutralize ring changes from collection-outage runs (append-only)."""
    import sqlite3
    from datetime import UTC, datetime

    from radar.orchestrator import RadarOrchestrator
    from radar.storage.history_log import append_events, load_events
    from radar.storage.history_repair import build_corrections, outage_run_ids

    orchestrator = RadarOrchestrator(root)
    orchestrator.history.initialize()
    # Legacy backfill only: if the log is missing/empty but the DB has real
    # history, this regenerates the log from the DB (see docs/persistence.md).
    # It does NOT make the DB authoritative going forward — the log below is.
    orchestrator.reconcile_history()
    # The durable JSONL log is truth, not the SQLite projection: both the
    # event stream corrections are derived from AND the "already corrected"
    # idempotence set must come from `load_events`, never from
    # `orchestrator.history.all_events()`. The DB can get ahead of the log
    # (e.g. a `corrected` marker written to the DB whose log append never
    # landed) — reading the DB there would make that drift permanently
    # unhealable, which is exactly the 2026-07-27 incident this guards against.
    events = load_events(orchestrator.history_log)
    try:
        outages = outage_run_ids(root / "data" / "radar.db")
    except sqlite3.OperationalError:
        # Fresh root: no scan has ever run, so source_health doesn't exist yet.
        console.print("No outage evidence recorded.")
        return
    corrections = build_corrections(events, outages, datetime.now(UTC))
    console.print(f"Outage runs detected: {len(outages)}")
    console.print(f"Corrections to append: {len(corrections)}")
    for c in corrections:
        previous_ring = c.previous_ring.value if c.previous_ring else "?"
        console.print(f"  {c.project}: {previous_ring} -> {c.ring.value} ({c.corrects_run_id})")
    if dry_run or not corrections:
        return
    # The log append is unconditional (it's the log's own idempotence check
    # above that decided these corrections are new); the DB insert is
    # deduped separately via import_events's natural key so a correction
    # already present in the DB (again, today's exact drift) isn't
    # double-inserted there.
    orchestrator.history.import_events(corrections)
    append_events(orchestrator.history_log, corrections)
    console.print(f"Appended {len(corrections)} corrected events.")
