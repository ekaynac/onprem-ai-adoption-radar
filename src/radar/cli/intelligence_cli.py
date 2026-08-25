"""Top-level ``radar intelligence-*`` commands.

Plain functions: the shared ``app`` in ``radar.cli`` registers them (in the
original cli.py order) via ``app.command("...")(...)``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from radar.cli._shared import console
from radar.intelligence.jobs import JobKind, JobService


def _execute_intelligence_job(root: Path, kind: JobKind) -> dict[str, Any]:
    import asyncio
    from dataclasses import asdict

    from radar.intelligence.bootstrap import build_intelligence_repository
    from radar.intelligence.pipeline import run_configured_job
    from radar.intelligence.scheduler import job_idempotency_key

    _database, repository = build_intelligence_repository(root)
    service = JobService(repository)
    now = datetime.now(UTC)
    idempotency_key = job_idempotency_key(kind, now)
    lease = service.acquire(kind, idempotency_key, now)
    if lease is None:
        return {
            "kind": kind.value,
            "idempotency_key": idempotency_key,
            "status": "skipped",
        }
    try:
        result = asyncio.run(
            run_configured_job(root, repository, kind, lease.id)
        )
        service.complete(lease.id, result, datetime.now(UTC))
    except Exception as exc:
        service.fail(lease.id, str(exc), datetime.now(UTC))
        raise
    return {
        "kind": kind.value,
        "idempotency_key": idempotency_key,
        "status": "completed",
        "result": asdict(result),
    }


def intelligence_migrate(
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Import legacy YAML and JSONL state into canonical intelligence storage."""
    from dataclasses import asdict

    from radar.intelligence.bootstrap import build_intelligence_repository
    from radar.intelligence.migration import import_legacy_state

    _database, repository = build_intelligence_repository(root)
    report = import_legacy_state(root, repository)
    console.print_json(data=asdict(report))


def intelligence_lineage_backfill(
    root: Path = typer.Option(Path("."), help="Project root."),
    fetch_limit: int = typer.Option(
        0,
        "--fetch-limit",
        help=(
            "Also query the HF baseModels expansion for up to N unchecked "
            "releases, highest downloads first (0 = replay stored claims only)."
        ),
    ),
    parent_limit: int = typer.Option(
        -1,
        "--parent-limit",
        help=(
            "Budget for registering declared parents missing from the index "
            "(-1 = same as --fetch-limit; 0 = skip parent registration)."
        ),
    ),
    max_minutes: float = typer.Option(
        0.0,
        "--max-minutes",
        help=(
            "Wall-clock budget for the network phases (0 = unlimited). On "
            "rate-limited days the run stops fetching cleanly at the "
            "deadline; later runs finish the tail."
        ),
    ),
) -> None:
    """Backfill model lineage edges and resolve root releases."""
    import asyncio

    from radar.intelligence.bootstrap import build_intelligence_repository
    from radar.intelligence.pipeline import run_lineage_backfill

    _database, repository = build_intelligence_repository(root)
    report = asyncio.run(
        run_lineage_backfill(
            root,
            repository,
            fetch_limit=fetch_limit,
            parent_limit=None if parent_limit < 0 else parent_limit,
            max_seconds=max_minutes * 60 if max_minutes > 0 else None,
        )
    )
    console.print_json(data=report)


def intelligence_lineage_triage(
    root: Path = typer.Option(Path("."), help="Project root."),
    fetch_limit: int = typer.Option(
        50,
        "--fetch-limit",
        help="Registry checks per run (reviews and suggestion children).",
    ),
    max_minutes: float = typer.Option(
        0.0,
        "--max-minutes",
        help="Wall-clock budget for the network phase (0 = unlimited).",
    ),
) -> None:
    """Evidence-driven triage of unresolved-parent reviews + suggestions.

    Checks each declared-but-untracked parent against the registry and
    corroborates Tier-3 suggestions against the child's own baseModels
    declaration; silent cards keep their suggestions for a human.
    """
    import asyncio

    from radar.intelligence.bootstrap import build_intelligence_repository
    from radar.intelligence.pipeline import run_lineage_triage

    _database, repository = build_intelligence_repository(root)
    report = asyncio.run(
        run_lineage_triage(
            root,
            repository,
            fetch_limit=fetch_limit,
            max_seconds=max_minutes * 60 if max_minutes > 0 else None,
        )
    )
    console.print_json(data=report)


def intelligence_shadow(
    root: Path = typer.Option(Path("."), help="Project root."),
    check: bool = typer.Option(
        False,
        "--check",
        help="Exit non-zero when canonical counts differ from legacy sources.",
    ),
) -> None:
    """Compare legacy source counts with canonical projections."""
    from dataclasses import asdict

    from radar.intelligence.bootstrap import build_intelligence_repository
    from radar.intelligence.shadow import compare_legacy_projection

    _database, repository = build_intelligence_repository(root)
    report = compare_legacy_projection(root, repository)
    payload = {**asdict(report), "is_equivalent": report.is_equivalent}
    console.print_json(data=payload)
    if check and not report.is_equivalent:
        raise typer.Exit(1)


def intelligence_replay_events(
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Replay the append-only intelligence event mirror into canonical storage."""
    from radar.intelligence.bootstrap import build_intelligence_repository
    from radar.intelligence.event_log import EventLog, replay_event_log

    _database, repository = build_intelligence_repository(root)
    count = replay_event_log(
        EventLog(root / "data" / "intelligence" / "events.jsonl"),
        repository,
    )
    console.print_json(data={"events_replayed": count})


def intelligence_state_pack(
    root: Path = typer.Option(Path("."), help="Project root."),
    out: Path = typer.Option(
        Path("build/intelligence-state.tar.gz"),
        "--out",
        help="Destination archive.",
    ),
) -> None:
    """Pack canonical intelligence state for durable workflow storage."""
    from dataclasses import asdict

    from radar.intelligence.state_bundle import pack_intelligence_state

    console.print_json(data=asdict(pack_intelligence_state(root, out)))


def intelligence_state_restore(
    root: Path = typer.Option(Path("."), help="Project root."),
    archive: Path = typer.Option(
        Path("build/intelligence-state.tar.gz"),
        "--archive",
        help="State archive to restore.",
    ),
) -> None:
    """Restore validated canonical intelligence workflow state."""
    from dataclasses import asdict

    from radar.intelligence.state_bundle import restore_intelligence_state

    console.print_json(data=asdict(restore_intelligence_state(root, archive)))


def intelligence_run(
    kind: JobKind = typer.Argument(..., help="Intelligence job kind."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Run one idempotent intelligence job for the current schedule window."""
    console.print_json(data=_execute_intelligence_job(root, kind))


def intelligence_scheduler(
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Run the built-in two-hour, daily, and weekly freshness schedule."""
    from threading import Event

    from radar.intelligence.scheduler import build_scheduler

    def run_scheduled(kind: JobKind) -> None:
        _execute_intelligence_job(root, kind)

    scheduler = build_scheduler(run_scheduled)
    scheduler.start()
    console.print("Intelligence scheduler started (UTC).")
    try:
        Event().wait()
    except KeyboardInterrupt:
        scheduler.shutdown(wait=True)
