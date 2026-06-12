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
