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
from radar.web.app import create_app


app = typer.Typer(
    help="Agent/tooling adoption radar for on-prem AI workflows.",
    no_args_is_help=True,
)
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


@app.command()
def report(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """Print a report from persisted cards."""
    cards = RadarOrchestrator(root).latest_cards()
    console.print(render_markdown_report(cards, "Agent/Tooling Adoption Radar"))


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
