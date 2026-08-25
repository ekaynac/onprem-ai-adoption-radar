"""``radar trending`` — trending & newly-created repos radar."""

from __future__ import annotations

from pathlib import Path

import typer

from radar.cli._shared import console


trending_app = typer.Typer(help="Trending & newly-created repos radar.", no_args_is_help=True)


@trending_app.command("scan")
def trending_scan(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """Sweep GitHub for trending/new repos and append to the observation log."""
    import asyncio
    import os
    from datetime import UTC, datetime

    import httpx

    from radar.discovery import trending_sweep
    from radar.discovery.trending_entities import Lane
    from radar.storage.config import load_config
    from radar.storage.trending_observations_log import append_observations

    config_path = root / "data" / "config.yaml"
    try:
        sources = load_config(config_path).sources
    except Exception as exc:
        console.print(f"[yellow]No config ({exc}); sweeping without exclusions.[/yellow]")
        sources = []

    def _headers() -> dict[str, str]:
        token = os.environ.get("GITHUB_TOKEN")
        return {"Authorization": f"Bearer {token}"} if token else {}

    now = datetime.now(UTC)

    async def _run():
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            return await trending_sweep.sweep_trending(
                sources, client, now=now, headers=_headers(),
            )

    observations = asyncio.run(_run())
    out_path = root / "data" / "trending-observations.jsonl"
    append_observations(out_path, observations)
    onprem = sum(1 for o in observations if o.lane == Lane.ONPREM)
    broader = len(observations) - onprem
    console.print(
        f"Observed {len(observations)} trending repo(s) "
        f"({onprem} on-prem / {broader} broader) → {out_path.relative_to(root)}"
    )


@trending_app.command("list")
def trending_list(
    root: Path = typer.Option(Path("."), help="Project root."),
    lane: str = typer.Option("", help="Filter by lane: onprem | broader."),
    new: bool = typer.Option(False, "--new", help="Only newly-created repos."),
) -> None:
    """List trending repos derived from the observation log."""
    from datetime import UTC, datetime

    from radar.discovery.trending_detect import build_trending
    from radar.discovery.trending_entities import Lane
    from radar.storage.trending_observations_log import load_observations

    if lane and lane not in (Lane.ONPREM.value, Lane.BROADER.value):
        console.print(f"[red]Unknown --lane: {lane} (use onprem | broader)[/red]")
        raise typer.Exit(code=1)

    path = root / "data" / "trending-observations.jsonl"
    entries = build_trending(load_observations(path), datetime.now(UTC))
    if not entries:
        console.print("No trending observations yet. Run [bold]radar trending scan[/bold] first.")
        return
    if lane:
        entries = [e for e in entries if e.lane.value == lane.lower()]
    if new:
        entries = [e for e in entries if e.is_new]
    console.print(f"{len(entries)} trending repo(s):")
    for e in entries:
        vel = f"{e.velocity_per_day:+.1f}/d" if e.velocity_per_day is not None else "   ?  "
        badge = "NEW" if e.is_new else "   "
        console.print(
            f"  {e.repo:<40} {e.stars:>7}★ {vel:<9} {badge} {e.lane.value:<8} "
            f"since {e.first_seen}",
            highlight=False, soft_wrap=True,
        )


@trending_app.command("promote")
def trending_promote(
    root: Path = typer.Option(Path("."), help="Project root."),
    limit: int = typer.Option(3, help="Max sources to auto-add per run."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print what would be added; do not write."),
) -> None:
    """Auto-add sustained-momentum strict-lane repos into config/seed-sources.yaml."""
    from datetime import UTC, datetime

    from radar.discovery.source_promotion import (
        build_source,
        is_promotable_source,
        momentum_stats,
        source_to_yaml_block,
    )
    from radar.discovery.trending_entities import Lane, TrendingObservation
    from radar.discovery.trending_sweep import _tracked_repos as _tracked_source_repos
    from radar.models import SourceConfig
    from radar.storage.autopilot_log import AutopilotEntry, append_autopilot
    from radar.storage.config import ConfigError, load_config
    from radar.storage.trending_observations_log import load_observations

    seed_path = root / "config" / "seed-sources.yaml"
    try:
        config = load_config(seed_path)
    except ConfigError as exc:
        console.print(f"[red]No source config to promote into: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    observations = load_observations(root / "data" / "trending-observations.jsonl")
    by_repo: dict[str, list[TrendingObservation]] = {}
    for obs in observations:
        by_repo.setdefault(obs.repo, []).append(obs)

    tracked_repos = _tracked_source_repos(config.sources)
    existing_ids = {s.id for s in config.sources}
    existing_projects = {s.project for s in config.sources}

    now = datetime.now(UTC)
    candidates = [
        (repo, rows) for repo, rows in by_repo.items()
        if is_promotable_source(repo, rows, tracked_repos=tracked_repos,
                                existing_ids=existing_ids, existing_projects=existing_projects,
                                now=now)
    ]

    def _velocity(rows: list[TrendingObservation]) -> float:
        stats = momentum_stats([r for r in rows if r.lane == Lane.ONPREM], now)
        return stats.avg_velocity if stats else 0.0

    candidates.sort(key=lambda rr: _velocity(rr[1]), reverse=True)

    collected: list[tuple[SourceConfig, list[TrendingObservation]]] = []
    working_ids = set(existing_ids)
    working_projects = {p.lower() for p in existing_projects}
    for repo, rows in candidates:
        if len(collected) >= limit:
            break
        source = build_source(repo, rows, existing_ids=working_ids)
        if source is None or source.project.lower() in working_projects:
            continue
        working_ids.add(source.id)
        working_projects.add(source.project.lower())
        collected.append((source, rows))

    if not collected:
        console.print("No sources qualified.")
        return

    if dry_run:
        from rich.table import Table

        table = Table(title="Would auto-add (dry run)")
        for col in ("id", "category", "stars", "velocity/day", "repo"):
            table.add_column(col)
        for source, rows in collected:
            latest = max(rows, key=lambda r: r.observed_at)
            table.add_row(source.id, source.category.value, str(latest.stars),
                          f"{_velocity(rows):.1f}", latest.repo)
        console.print(table)
        return

    from radar.discovery.source_promotion import splice_into_sources

    old_text = seed_path.read_text(encoding="utf-8")
    block_text = "".join(source_to_yaml_block(s) for s, _ in collected)
    new_text = splice_into_sources(old_text, block_text)

    tmp = seed_path.with_suffix(".promote.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    try:
        loaded = load_config(tmp)
    except ConfigError as exc:
        tmp.unlink(missing_ok=True)
        console.print(f"[red]Validation failed: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    loaded_ids = [s.id for s in loaded.sources]
    if len(loaded_ids) != len(set(loaded_ids)):
        tmp.unlink(missing_ok=True)
        console.print("[red]Validation failed: duplicate source ids after append[/red]")
        raise typer.Exit(code=1)
    tmp.replace(seed_path)

    now = datetime.now(UTC)
    append_autopilot(root / "data" / "autopilot-log.jsonl", [
        AutopilotEntry(
            repo=max(rows, key=lambda r: r.observed_at).repo, source_id=source.id,
            category=source.category.value,
            stars=max(rows, key=lambda r: r.observed_at).stars,
            avg_velocity=_velocity(rows), added_at=now,
        )
        for source, rows in collected
    ])
    console.print(f"Promoted {len(collected)} source(s) into {seed_path.relative_to(root)}")
