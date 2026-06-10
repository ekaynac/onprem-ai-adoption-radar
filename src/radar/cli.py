"""Command line interface for the adoption radar."""

from __future__ import annotations

import typer
from rich.console import Console

from radar import __version__
from radar.constants import APP_NAME


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


def main() -> None:
    """Entrypoint for the installed console script."""
    app()
