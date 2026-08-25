"""``radar desk`` — analyst desk: weekly brief + public calls ledger."""

from __future__ import annotations

from pathlib import Path

import typer

from radar.cli._shared import console


desk_app = typer.Typer(
    help="Analyst desk: weekly brief + public calls ledger.",
    no_args_is_help=True,
)


@desk_app.command("brief")
def desk_brief(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """Build this week's brief and record its new calls (idempotent per week)."""
    import json as json_module
    from datetime import UTC, datetime

    from radar.reports.brief import build_brief
    from radar.storage.calls_ledger import (
        CallRecord,
        append_call_records,
        load_call_records,
    )

    now = datetime.now(UTC)
    brief = build_brief(root, now)
    briefs_dir = root / "data" / "briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)
    brief_path = briefs_dir / f"{brief['id']}.json"
    brief_path.write_text(
        json_module.dumps(brief, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )

    ledger_path = root / "data" / "calls-ledger.jsonl"
    existing = {
        record.call_id
        for record in load_call_records(ledger_path)
        if record.type == "made"
    }
    new_calls = [
        CallRecord(
            type="made",
            call_id=item["id"],
            recorded_at=now,
            brief_id=brief["id"],
            subject=item["subject"],
            verdict=item["verdict"],
            rationale=item["rationale"],
        )
        for item in brief["items"]
        if item["id"] not in existing
    ]
    append_call_records(ledger_path, new_calls)
    console.print(
        f"Brief {brief['id']}: {len(brief['items'])} item(s) "
        f"({brief['verdict_counts']}) → {brief_path.relative_to(root)}; "
        f"{len(new_calls)} new call(s) recorded"
    )


@desk_app.command("auto-resolve")
def desk_auto_resolve(
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Score open calls by the documented deterministic rules (v1).

    Ring-move calls confirm/fail after a 14-day hold window against
    subsequent ring history; other calls expire at 28 days. Calls
    younger than their window stay open — nothing is scored early.
    """
    from datetime import UTC, datetime

    from radar.reports.call_resolution import auto_resolve_calls
    from radar.storage.calls_ledger import (
        append_call_records,
        fold_calls,
        load_call_records,
    )

    ledger_path = root / "data" / "calls-ledger.jsonl"
    states = fold_calls(load_call_records(ledger_path))
    now = datetime.now(UTC)
    resolutions = auto_resolve_calls(root, states, now)
    append_call_records(ledger_path, resolutions)
    outcomes: dict[str, int] = {}
    for record in resolutions:
        outcomes[record.outcome or "?"] = outcomes.get(record.outcome or "?", 0) + 1
    open_count = sum(1 for state in states if state.status == "open")
    console.print(
        f"Auto-resolved {len(resolutions)} call(s) {outcomes or ''} — "
        f"{open_count - len(resolutions)} still open (inside their windows)"
    )


@desk_app.command("resolve")
def desk_resolve(
    call_id: str = typer.Argument(..., help="Call id from the ledger."),
    outcome: str = typer.Option(..., "--outcome", help="confirmed | wrong | expired"),
    note: str = typer.Option("", "--note", help="Resolution note (receipts welcome)."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Resolve a public call; the ledger keeps score, nothing is edited."""
    from datetime import UTC, datetime

    from radar.storage.calls_ledger import (
        CallRecord,
        append_call_records,
        fold_calls,
        load_call_records,
    )

    ledger_path = root / "data" / "calls-ledger.jsonl"
    states = {state.call_id: state for state in fold_calls(load_call_records(ledger_path))}
    state = states.get(call_id)
    if state is None:
        console.print(f"[red]Unknown call: {call_id}[/red]")
        raise typer.Exit(code=1)
    if state.status != "open":
        console.print(f"[yellow]{call_id} already {state.status}[/yellow]")
        raise typer.Exit(code=1)
    if outcome not in {"confirmed", "wrong", "expired"}:
        console.print(f"[red]Invalid outcome: {outcome}[/red]")
        raise typer.Exit(code=1)
    append_call_records(
        ledger_path,
        [
            CallRecord(
                type="resolved",
                call_id=call_id,
                recorded_at=datetime.now(UTC),
                outcome=outcome,
                note=note or None,
            )
        ],
    )
    console.print(f"{call_id} → {outcome}")


@desk_app.command("calls")
def desk_calls(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """List calls with the public track record."""
    from radar.storage.calls_ledger import (
        fold_calls,
        load_call_records,
        track_record,
    )

    states = fold_calls(
        load_call_records(root / "data" / "calls-ledger.jsonl")
    )
    console.print_json(data={"track_record": track_record(states)})
    for state in states[:20]:
        console.print(
            f"  [{state.status}] {state.verdict} {state.subject} — "
            f"{state.rationale} ({state.call_id})"
        )
