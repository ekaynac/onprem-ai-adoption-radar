"""Command line interface for the adoption radar."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from radar import __version__
from radar.constants import APP_NAME
from radar.init_project import initialize_project


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


def main() -> None:
    """Entrypoint for the installed console script."""
    app()
