"""``radar pulse`` — what's new for an AI developer: models, papers, repos, news."""

from __future__ import annotations

from pathlib import Path

import typer

from radar.cli._shared import BUNDLED_ROOT, console


pulse_app = typer.Typer(
    help="Radar Pulse: new models, papers, repos and news in one feed.",
    no_args_is_help=True,
)


def _pulse_config_path(root: Path) -> Path:
    path = root / "config" / "pulse.yaml"
    return path if path.exists() else BUNDLED_ROOT / "config" / "pulse.yaml"


@pulse_app.command("collect")
def pulse_collect(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """Fetch lab models + daily papers, fold in repo/news logs, update the item store."""
    import asyncio
    from datetime import UTC, datetime

    import httpx

    from radar.huggingface_auth import hf_auth_headers
    from radar.pulse.config import load_pulse_config
    from radar.pulse.pipeline import ITEMS_PATH, collect
    from radar.storage.source_health_log import (
        SourceHealthRecord,
        SourceOutcome,
        append_source_health,
    )

    config = load_pulse_config(_pulse_config_path(root))
    now = datetime.now(UTC)

    async def _run():
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            return await collect(root, config, client, now, hf_headers=hf_auth_headers(root))

    report = asyncio.run(_run())
    append_source_health(
        root / "data" / "source-health.jsonl",
        SourceHealthRecord(
            run_id=f"pulse-{now.isoformat()}",
            observed_at=now,
            sources={
                run.source: SourceOutcome(count=len(run.items), status=run.status)
                for run in report.runs
            },
        ),
    )

    for run in report.runs:
        style = {"ok": "green", "partial": "yellow", "error": "red"}[run.status]
        console.print(f"[{style}]{run.source}: {run.status}, {len(run.items)} items[/{style}]")
        for error in run.errors:
            console.print(f"  [yellow]{error}[/yellow]")
    lanes = ", ".join(f"{lane}={n}" for lane, n in sorted(report.lane_counts.items()))
    origins = ", ".join(f"{k}={n}" for k, n in sorted(report.model_origin_counts.items()))
    console.print(f"Pulse store {root / ITEMS_PATH}: {lanes}")
    console.print(f"Model origins: {origins}")
    if report.all_network_sources_failed:
        console.print("[red]Every Pulse network source failed this run.[/red]")
        raise typer.Exit(code=1)
