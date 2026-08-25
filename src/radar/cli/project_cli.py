"""Core project commands: version/backtest/init/scan/discover + pin/trial/sandbox.

Plain functions: the shared ``app`` in ``radar.cli`` registers them (in the
original cli.py order) via ``app.command(...)`` / ``app.callback()``.
"""

from __future__ import annotations

from datetime import UTC
from pathlib import Path
from typing import Any

import typer
import uvicorn

from radar import __version__
from radar.cli._shared import console
from radar.constants import APP_NAME
from radar.init_project import initialize_project
from radar.orchestrator import RadarOrchestrator
from radar.scoring.profiles import UnknownProfileError
from radar.web.app import create_app


def root() -> None:
    """Agent/tooling adoption radar for on-prem AI workflows."""


def version() -> None:
    """Print package version."""
    console.print(f"{APP_NAME} {__version__}")


def backtest(
    profile: str = typer.Option(
        "", help="Compare this profile's weights vs the default across past runs."
    ),
    runs: int = typer.Option(0, help="Limit to the N most recent runs (0 = all)."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Re-score historical runs and report how rings would differ (read-only)."""
    from radar.analysis.backtest import render_backtest_markdown

    try:
        report = RadarOrchestrator(root).backtest(
            profile=profile or None, runs=runs or None
        )
    except UnknownProfileError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(render_backtest_markdown(report))


def init(
    root: Path = typer.Option(Path("."), help="Project root to initialize."),
    force: bool = typer.Option(
        False,
        "--force",
        help="Refresh config.yaml from the bundled seed (backs up the existing one).",
    ),
) -> None:
    """Create starter config and data directories."""
    result = initialize_project(root, force=force)
    console.print(f"Config: {result.config_path}")
    if result.config_refreshed and result.backup_path is not None:
        console.print(f"[yellow]Config refreshed from seed.[/yellow] Backup: {result.backup_path}")
    elif not result.config_refreshed:
        console.print("[dim]Config already exists; left unchanged (use --force to refresh).[/dim]")
    console.print(f"Env example: {result.env_example_path}")
    console.print(f"Runs: {result.runs_path}")


def scan(
    days: int = typer.Option(2, min=1, help="Look back this many days."),
    replay: str = typer.Option(
        "", help="Re-score a past run's raw signals offline with CURRENT config."
    ),
    profile: str = typer.Option(
        "", help="Score through a named profile from config (re-weighted dimensions)."
    ),
    publish_history: bool = typer.Option(
        False,
        "--publish-history",
        help="Append ring changes to the committed data/history.jsonl (CI only).",
    ),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Collect signals, score them, and write run artifacts."""
    if replay:
        try:
            replay_result = RadarOrchestrator(root).replay(replay)
        except FileNotFoundError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from exc
        console.print(f"Replay run: {replay_result.run_id} (of {replay})")
        console.print(f"Cards: {len(replay_result.cards)}")
        console.print(f"Report: {replay_result.report_path}")
        console.print("(Offline replay: no history, metrics, or card DB changes.)")
        return
    orchestrator = RadarOrchestrator(root)
    try:
        result = orchestrator.scan(
            days=days, profile=profile or None, publish_history=publish_history
        )
    except UnknownProfileError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if result.degraded:
        console.print(f"[red]DEGRADED:[/red] {result.degraded_reason}")
        console.print("No cards, history, or metrics were written.")
        raise typer.Exit(code=2)
    console.print(f"Run: {result.run_id}")
    console.print(f"Cards: {len(result.cards)}")
    console.print(f"Report: {result.report_path}")
    console.print(f"Changed since last scan: {len(result.deltas)}")
    console.print(f"Try This Week: {result.delta_report_path}")
    console.print(f"History: {result.history_report_path}")

    from radar.web.scan_health import summarize_meta

    health = summarize_meta(orchestrator.run_store.read_meta(result.run_id))
    console.print(health.one_line)


def discover(
    category: str = typer.Option("", help="Limit discovery to one category."),
    min_stars: int = typer.Option(500, help="Minimum stars for a candidate."),
    since_days: int = typer.Option(30, help="Only repos pushed within this many days."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Find trending GitHub repos and write proposals for review (never auto-adds)."""
    import asyncio

    import httpx

    from radar.discovery.github_trending import discover_trending
    from radar.discovery.hf_papers import discover_from_hf_papers
    from radar.discovery.proposals import write_proposals
    from radar.models import Category
    from radar.storage.config import load_config

    config_path = root / "data" / "config.yaml"
    if not config_path.exists():
        console.print(
            f"[red]No config at {config_path}.[/red] Run [bold]radar init[/bold] first."
        )
        raise typer.Exit(code=1)
    config = load_config(config_path)

    if category:
        try:
            categories = [Category(category)]
        except ValueError as exc:
            console.print(f"[red]Unknown category:[/red] {category}")
            raise typer.Exit(code=1) from exc
    else:
        categories = list(Category)

    def _headers() -> dict[str, str]:
        import os

        headers = {"Accept": "application/vnd.github+json", "User-Agent": APP_NAME}
        token = os.getenv("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def _run():
        async with httpx.AsyncClient(timeout=30.0) as client:
            trending = await discover_trending(
                config.sources, client, categories=categories,
                min_stars=min_stars, since_days=since_days, headers=_headers(),
            )
            hf = await discover_from_hf_papers(
                config.sources, client, min_stars=min_stars, headers=_headers(),
            )
            merged: dict[str, Any] = {p.url: p for p in hf}
            for proposal in trending:  # trending overrides HF on URL collision
                merged[proposal.url] = proposal
            return sorted(merged.values(), key=lambda p: p.stars, reverse=True)

    proposals = asyncio.run(_run())
    out_path = root / "data" / "proposed-seeds.yaml"
    write_proposals(out_path, proposals)
    console.print(f"Found {len(proposals)} candidate(s) → {out_path}")
    for proposal in proposals[:15]:
        console.print(
            f"  {proposal.stars:>6}★  {proposal.project:<24} {proposal.category.value:<22} "
            f"{proposal.url}",
            highlight=False,
            soft_wrap=True,
        )
    if proposals:
        console.print(
            "Review them, then add the good ones with [bold]radar seed add[/bold]."
        )


def override(
    project: str = typer.Option(..., help="Project whose ring to pin."),
    ring: str = typer.Option("", help="Ring to pin: adopt, pilot, watch, or avoid."),
    reason: str = typer.Option("", help="Why this pin exists (required when pinning)."),
    clear: bool = typer.Option(False, "--clear", help="Remove the project's pin."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Pin a project's ring (your decision wins; drift vs the radar is surfaced)."""
    from datetime import datetime

    from radar.storage.overrides_store import OverridesStore, RingOverride

    store = OverridesStore(root / "data" / "overrides.yaml")
    if clear:
        if store.clear_override(project):
            console.print(f"Cleared pin for {project}. Next scan returns it to computed rings.")
        else:
            console.print(f"[yellow]No pin existed for {project}.[/yellow]")
        _repin_stored_card(root, project, None, "")
        return

    from radar.models import Ring as RingEnum

    try:
        pinned_ring = RingEnum(ring)
    except ValueError as exc:
        console.print(f"[red]Unknown ring:[/red] {ring or '(missing)'} — use adopt/pilot/watch/avoid.")
        raise typer.Exit(code=1) from exc
    if not reason.strip():
        console.print("[red]A pin needs a --reason.[/red] Future-you will want to know why.")
        raise typer.Exit(code=1)

    store.set_override(
        RingOverride(
            project=project,
            ring=pinned_ring,
            reason=reason.strip(),
            set_at=datetime.now(UTC),
        )
    )
    console.print(f"Pinned {project} to [bold]{pinned_ring.value}[/bold]: {reason.strip()}")
    _repin_stored_card(root, project, pinned_ring, reason.strip())


def _repin_stored_card(root: Path, project: str, ring, reason: str) -> None:
    """Apply/clear a pin on the persisted card immediately and journal the move."""
    from datetime import datetime

    from radar.pipeline.delta import compute_deltas
    from radar.storage.database import RadarDatabase
    from radar.storage.history_log import append_events
    from radar.storage.history_store import HistoryStore, deltas_to_events

    db = RadarDatabase(root / "data" / "radar.db")
    db.initialize()
    cards = db.list_cards()
    card = next((c for c in cards if c.project == project), None)
    if card is None:
        console.print("(No scanned card yet — the pin applies from the next scan.)")
        return

    if ring is None:  # clearing: restore the computed ring if we have one
        restored_ring = card.computed_ring or card.ring
        updated = card.model_copy(
            update={
                "ring": restored_ring,
                "pinned": False,
                "pinned_reason": "",
                "computed_ring": None,
            }
        )
    else:
        updated = card.model_copy(
            update={
                "ring": ring,
                "pinned": True,
                "pinned_reason": reason,
                "computed_ring": card.computed_ring or card.ring,
            }
        )
    if updated.ring == card.ring:
        db.upsert_cards([updated])
        return

    deltas = compute_deltas(previous=[card], current=[updated])
    db.upsert_cards([updated])
    now = datetime.now(UTC)
    run_id = f"override-{now:%Y%m%dT%H%M%SZ}"
    history = HistoryStore(root / "data" / "radar.db")
    history.initialize()
    events = deltas_to_events(deltas, run_id=run_id, observed_at=now)
    history.add_events(events)
    append_events(root / "data" / "history.jsonl", events)
    console.print(f"Card updated: {card.ring.value} → {updated.ring.value} (journaled).")


def trial(
    project: str = typer.Option(..., help="Project you trialed."),
    outcome: str = typer.Option(..., help="adopted, rejected, or inconclusive."),
    notes: str = typer.Option("", help="What you observed."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Record a sandbox-trial outcome in the decision journal (and timeline)."""
    from datetime import datetime

    from radar.storage.overrides_store import OverridesStore, TrialRecord

    store = OverridesStore(root / "data" / "overrides.yaml")
    try:
        record = TrialRecord(
            project=project,
            outcome=outcome,
            notes=notes.strip(),
            recorded_at=datetime.now(UTC),
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    store.add_trial(record)
    _journal_trial(root, record)
    console.print(f"Recorded trial for {project}: [bold]{outcome}[/bold].")


def _journal_trial(root: Path, record) -> None:
    """Append the trial to the project's timeline when the project is tracked."""
    from radar.pipeline.delta import ChangeType
    from radar.storage.database import RadarDatabase
    from radar.storage.history_log import append_events
    from radar.storage.history_store import HistoryStore, ProjectHistoryEvent

    db = RadarDatabase(root / "data" / "radar.db")
    db.initialize()
    card = next((c for c in db.list_cards() if c.project == record.project), None)
    if card is None:
        console.print("(Project has no card yet — journaled in overrides.yaml only.)")
        return
    reason = f"Trial {record.outcome}" + (f": {record.notes}" if record.notes else ".")
    event = ProjectHistoryEvent(
        project=record.project,
        category=card.category,
        change_type=ChangeType.UPDATED,
        ring=card.ring,
        previous_ring=card.ring,
        run_id=f"trial-{record.recorded_at:%Y%m%dT%H%M%SZ}",
        observed_at=record.recorded_at,
        reasons=[reason],
    )
    history = HistoryStore(root / "data" / "radar.db")
    history.initialize()
    history.add_events([event])
    append_events(root / "data" / "history.jsonl", [event])


def sandbox(
    project: str = typer.Option(..., help="Project to generate a trial plan for."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Print a safe, disposable sandbox trial plan for a project."""
    from radar.reports.sandbox import build_sandbox_plan, render_sandbox_markdown

    cards = RadarOrchestrator(root).latest_cards()
    card = next((c for c in cards if c.project == project), None)
    if card is None:
        console.print(f"[red]Unknown project:[/red] {project}")
        raise typer.Exit(code=1)
    console.print(render_sandbox_markdown(card, build_sandbox_plan(card)))


def compare(
    projects: str = typer.Option("", help="Comma-separated project names to compare."),
    category: str = typer.Option("", help="Compare all projects in this category."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Print a side-by-side comparison matrix."""
    from radar.models import Category
    from radar.reports.comparison import (
        ComparisonError,
        build_comparison,
        render_comparison_markdown,
    )

    cards = RadarOrchestrator(root).latest_cards()
    project_list = [p.strip() for p in projects.split(",") if p.strip()] or None
    cat = None
    title = "Comparison"
    if category:
        try:
            cat = Category(category)
        except ValueError as exc:
            console.print(f"[red]Unknown category:[/red] {category}")
            raise typer.Exit(code=1) from exc
        title = f"Comparison: {category}"
    elif project_list:
        title = "Comparison: " + " vs ".join(project_list)

    try:
        comparison = build_comparison(cards, projects=project_list, category=cat)
    except ComparisonError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(render_comparison_markdown(comparison, title))


def mcp(
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Run the MCP server (stdio) so agents can query the radar."""
    from radar.mcp_server.server import run as run_mcp

    run_mcp(root)


def serve(
    root: Path = typer.Option(Path("."), help="Project root."),
    host: str = typer.Option("127.0.0.1", help="Bind host."),
    port: int = typer.Option(8765, help="Bind port."),
) -> None:
    """Serve the local dashboard."""
    uvicorn.run(create_app(root), host=host, port=port)
