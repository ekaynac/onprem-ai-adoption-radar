"""``radar seed`` — manage signal sources (seeds)."""

from __future__ import annotations

from pathlib import Path

import typer

from radar.cli._shared import console
from radar.storage.seed_store import SeedError, add_seed


seed_app = typer.Typer(help="Manage signal sources (seeds).", no_args_is_help=True)


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
    """List the configured signal sources (stale = no signals for 7+ scans)."""
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
