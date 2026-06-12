"""Command line interface for the adoption radar."""

from __future__ import annotations

from pathlib import Path

import typer
import uvicorn
from rich.console import Console

from radar import __version__
from radar.constants import APP_NAME
from radar.init_project import initialize_project
from radar.orchestrator import RadarOrchestrator
from radar.reports.markdown import render_markdown_report
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
def init(root: Path = typer.Option(Path("."), help="Project root to initialize.")) -> None:
    """Create starter config and data directories."""
    result = initialize_project(root)
    console.print(f"Config: {result.config_path}")
    console.print(f"Env example: {result.env_example_path}")
    console.print(f"Runs: {result.runs_path}")


@app.command()
def scan(
    days: int = typer.Option(2, min=1, help="Look back this many days."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Collect signals, score them, and write run artifacts."""
    result = RadarOrchestrator(root).scan(days=days)
    console.print(f"Run: {result.run_id}")
    console.print(f"Cards: {len(result.cards)}")
    console.print(f"Report: {result.report_path}")
    console.print(f"Changed since last scan: {len(result.deltas)}")
    console.print(f"Try This Week: {result.delta_report_path}")
    console.print(f"History: {result.history_report_path}")


@app.command()
def report(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """Print a report from persisted cards."""
    cards = RadarOrchestrator(root).latest_cards()
    console.print(render_markdown_report(cards, "Agent/Tooling Adoption Radar"))


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
        raise typer.Exit(code=1)
    console.print(f"Added source: {source.id} ({source.type.value} -> {source.category.value})")


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
    from datetime import datetime, timezone

    from radar.web.static_site import render_static_site

    cards = RadarOrchestrator(root).latest_cards()
    index = render_static_site(cards, out, datetime.now(timezone.utc))
    console.print(f"Wrote {index} ({len(cards)} cards)")


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
        except ValueError:
            console.print(f"[red]Unknown category:[/red] {category}")
            raise typer.Exit(code=1)
        title = f"Comparison: {category}"
    elif project_list:
        title = "Comparison: " + " vs ".join(project_list)

    try:
        comparison = build_comparison(cards, projects=project_list, category=cat)
    except ComparisonError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
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
