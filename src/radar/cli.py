"""Command line interface for the adoption radar."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

import typer
import uvicorn
from rich.console import Console

from radar import __version__
from radar.constants import APP_NAME
from radar.init_project import initialize_project
from radar.orchestrator import RadarOrchestrator
from radar.reports.markdown import render_markdown_report
from radar.scoring.profiles import UnknownProfileError
from radar.storage.seed_store import SeedError, add_seed
from radar.web.app import create_app


app = typer.Typer(
    help="Agent/tooling adoption radar for on-prem AI workflows.",
    no_args_is_help=True,
)
seed_app = typer.Typer(help="Manage signal sources (seeds).", no_args_is_help=True)
app.add_typer(seed_app, name="seed")
console = Console()


@app.callback()
def root() -> None:
    """Agent/tooling adoption radar for on-prem AI workflows."""


@app.command()
def version() -> None:
    """Print package version."""
    console.print(f"{APP_NAME} {__version__}")


@app.command()
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


@app.command()
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


@app.command()
def scan(
    days: int = typer.Option(2, min=1, help="Look back this many days."),
    replay: str = typer.Option(
        "", help="Re-score a past run's raw signals offline with CURRENT config."
    ),
    profile: str = typer.Option(
        "", help="Score through a named profile from config (re-weighted dimensions)."
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
        result = orchestrator.scan(days=days, profile=profile or None)
    except UnknownProfileError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"Run: {result.run_id}")
    console.print(f"Cards: {len(result.cards)}")
    console.print(f"Report: {result.report_path}")
    console.print(f"Changed since last scan: {len(result.deltas)}")
    console.print(f"Try This Week: {result.delta_report_path}")
    console.print(f"History: {result.history_report_path}")

    from radar.web.scan_health import summarize_meta

    health = summarize_meta(orchestrator.run_store.read_meta(result.run_id))
    console.print(health.one_line)


@app.command()
def report(
    root: Path = typer.Option(Path("."), help="Project root."),
    as_json: bool = typer.Option(False, "--json", help="Emit cards as JSON for scripting."),
    profile: str = typer.Option(
        "", help="Re-rank the view through a named profile (does not persist)."
    ),
) -> None:
    """Print a report from persisted cards."""
    try:
        cards = RadarOrchestrator(root).latest_cards(profile=profile or None)
    except UnknownProfileError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if as_json:
        from radar.reports.json_export import cards_to_json

        # print, not console.print: rich would wrap/highlight the payload.
        print(cards_to_json(cards))
        return
    title = "Agent/Tooling Adoption Radar"
    if profile:
        title += f" — {profile} profile"
    console.print(render_markdown_report(cards, title))


@seed_app.command("add")
def seed_add(
    id: str = typer.Option(..., help="Unique source id, e.g. rss-nvidia-dev-blog."),
    type: str = typer.Option(..., help="Source type: github_repo, rss, or manual."),
    project: str = typer.Option(..., help="Display name for the project/stream."),
    category: str = typer.Option(..., help="Radar category, e.g. model_serving."),
    url: str = typer.Option(..., help="Source URL (repo, feed, or page)."),
    tags: str = typer.Option("", help="Comma-separated tags."),
    enabled: bool = typer.Option(True, help="Whether the source is active."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Add a new signal source to the project config."""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    config_path = root / "data" / "config.yaml"
    try:
        source = add_seed(
            config_path,
            {
                "id": id,
                "type": type,
                "project": project,
                "category": category,
                "url": url,
                "tags": tag_list,
                "enabled": enabled,
            },
        )
    except SeedError as exc:
        console.print(f"[red]Could not add source:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"Added source: {source.id} ({source.type.value} -> {source.category.value})")


@seed_app.command("list")
def seed_list(
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """List the configured signal sources (stale = no signals for 3+ scans)."""
    from radar.storage.config import load_config
    from radar.storage.source_health_store import SourceHealthStore

    config_path = root / "data" / "config.yaml"
    if not config_path.exists():
        console.print(
            f"[red]No config at {config_path}.[/red] Run [bold]radar init[/bold] first."
        )
        raise typer.Exit(code=1)
    config = load_config(config_path)

    health = SourceHealthStore(root / "data" / "radar.db")
    health.initialize()
    stale = health.stale_source_ids()
    latest = health.latest_counts()

    stale_note = f" — {len(stale)} stale" if stale else ""
    console.print(f"{len(config.sources)} sources in {config_path}{stale_note}")
    # Plain aligned text (no rich table): never truncated, grep/pipe friendly.
    for source in config.sources:
        flags = []
        if not source.enabled:
            flags.append("disabled")
        if source.firehose:
            flags.append("firehose")
        if source.id in stale:
            flags.append("STALE?")
        elif source.id in latest:
            flags.append(f"last={latest[source.id]}")
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        # soft_wrap: keep each source on one line (never truncated/wrapped) so
        # the output stays grep- and pipe-friendly.
        console.print(
            f"  {source.id:<28} {source.type.value:<12} {source.category.value:<26} "
            f"{source.project}{suffix}",
            highlight=False,
            soft_wrap=True,
        )


@app.command()
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
            return await discover_trending(
                config.sources,
                client,
                categories=categories,
                min_stars=min_stars,
                since_days=since_days,
                headers=_headers(),
            )

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


@app.command()
def history(
    project: str = typer.Option("", help="Limit to a single project (optional)."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Print the cumulative per-project observation history."""
    from radar.reports.history import render_history_report
    from radar.storage.history_store import HistoryStore

    store = HistoryStore(root / "data" / "radar.db")
    store.initialize()
    summaries = store.summaries()
    if project:
        summaries = [s for s in summaries if s.project == project]
    events = {s.project: store.history_for(s.project) for s in summaries}
    console.print(render_history_report(summaries, events, "Adoption History"))


@app.command()
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


@app.command()
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


@app.command("calibrate-report")
def calibrate_report(
    root: Path = typer.Option(Path("."), help="Project root."),
    check: bool = typer.Option(
        False, "--check", help="Exit non-zero if the rings do not discriminate (CI gate)."
    ),
) -> None:
    """Diagnose whether the scoring discriminates and is stable over time."""
    from radar.analysis.calibration import (
        build_calibration_report,
        render_calibration_markdown,
    )
    from radar.models import ScoredSignal
    from radar.storage.database import RadarDatabase
    from radar.storage.history_store import HistoryStore

    db = RadarDatabase(root / "data" / "radar.db")
    db.initialize()
    cards = db.list_cards()
    if not cards:
        console.print("No cards yet. Run [bold]radar scan[/bold] first.")
        raise typer.Exit(code=1)
    ring_by_project = {c.project: c.ring for c in cards}

    # Re-score the latest run's persisted signals for the per-dimension detail
    # (cards keep only the representative aggregate + breakdown).
    scored = _latest_scored_signals(root)
    if scored is None:
        # Fall back to card breakdowns when the run artifact is unavailable.
        scored = [
            ScoredSignal(
                signal=_synthetic_signal(c),
                scores=c.score_breakdown,
                recommended_ring=c.ring,
            )
            for c in cards
            if c.score_breakdown is not None
        ]

    history = HistoryStore(root / "data" / "radar.db")
    history.initialize()
    events = [e for s in history.summaries() for e in history.history_for(s.project)]

    report = build_calibration_report(scored, ring_by_project, history_events=events)
    console.print(render_calibration_markdown(report))
    # Quality gate: fail only on collapse (one ring, or >80% in a single ring),
    # which means scoring stopped discriminating — a real regression.
    if check and not report.discriminates:
        console.print(
            "[red]Quality gate failed:[/red] rings do not discriminate."
        )
        raise typer.Exit(code=1)


def _latest_scored_signals(root: Path):
    """Load the most recent run's scored_signals, or None if unavailable."""
    from radar.models import ScoredSignal

    runs_dir = root / "data" / "runs"
    if not runs_dir.exists():
        return None
    run_dirs = sorted(
        (d for d in runs_dir.iterdir() if (d / "scored_signals.json").exists()),
        key=lambda d: d.name,
        reverse=True,
    )
    if not run_dirs:
        return None
    import json

    payload = json.loads(
        (run_dirs[0] / "scored_signals.json").read_text(encoding="utf-8")
    )
    return [ScoredSignal.model_validate(item) for item in payload]


def _synthetic_signal(card):
    """A minimal Signal so a card breakdown can be wrapped as a ScoredSignal."""
    from datetime import datetime

    from radar.models import Signal

    return Signal(
        id=card.project, source_id="card", project=card.project,
        category=card.category, title=card.project,
        url="https://example.invalid", signal_type="card",
        published_at=datetime.now(UTC),
    )


@app.command()
def movers(
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Show each project's direction of travel (rising / falling / steady)."""
    from radar.pipeline.momentum import compute_momentum, trend_arrow
    from radar.storage.history_store import HistoryStore
    from radar.storage.metrics_store import MetricsStore

    history = HistoryStore(root / "data" / "radar.db")
    history.initialize()
    metrics = MetricsStore(root / "data" / "radar.db")
    metrics.initialize()

    summaries = history.summaries()
    if not summaries:
        console.print("No history yet. Run [bold]radar scan[/bold] first.")
        raise typer.Exit(code=1)

    momentums = [
        compute_momentum(
            s.project,
            metric_rows=metrics.history_for(s.project),
            ring_events=history.history_for(s.project),
        )
        for s in summaries
    ]
    order = {"rising": 0, "falling": 1, "steady": 2}
    momentums.sort(key=lambda m: (order.get(m.direction, 3), -(m.star_growth_pct or 0)))
    for momentum in momentums:
        note = f"  {momentum.note}" if momentum.note else ""
        console.print(
            f"  {trend_arrow(momentum.direction)} {momentum.project:<28} "
            f"{momentum.direction:<8}{note}",
            highlight=False,
        )


@app.command()
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


@app.command()
def export(
    out: Path = typer.Option(Path("_site"), help="Output directory for static HTML."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Render a static HTML snapshot (for GitHub Pages) from the latest scan."""
    from datetime import datetime

    from radar.storage.history_store import HistoryStore
    from radar.storage.metrics_store import MetricsStore
    from radar.web.static_site import render_static_site

    orchestrator = RadarOrchestrator(root)
    cards = orchestrator.latest_cards()

    history = HistoryStore(root / "data" / "radar.db")
    history.initialize()
    timelines = [
        {"summary": s, "events": history.history_for(s.project)}
        for s in sorted(history.summaries(), key=lambda s: s.last_change_at, reverse=True)
    ]

    metrics = MetricsStore(root / "data" / "radar.db")
    metrics.initialize()
    metrics_by_project = {c.project: metrics.history_for(c.project) for c in cards}

    run_ids = orchestrator.run_store.list_runs()
    latest_scan_meta = orchestrator.run_store.read_meta(run_ids[-1]) if run_ids else {}

    index = render_static_site(
        cards,
        out,
        datetime.now(UTC),
        timelines=timelines,
        metrics_by_project=metrics_by_project,
        latest_scan_meta=latest_scan_meta,
    )
    console.print(
        f"Wrote {index.parent}/ (index, compare, history, {len(cards)} project pages)"
    )


@app.command()
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


@app.command()
def mcp(
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Run the MCP server (stdio) so agents can query the radar."""
    from radar.mcp_server.server import run as run_mcp

    run_mcp(root)


@app.command()
def serve(
    root: Path = typer.Option(Path("."), help="Project root."),
    host: str = typer.Option("127.0.0.1", help="Bind host."),
    port: int = typer.Option(8765, help="Bind port."),
) -> None:
    """Serve the local dashboard."""
    uvicorn.run(create_app(root), host=host, port=port)


def main() -> None:
    """Entrypoint for the installed console script."""
    app()
