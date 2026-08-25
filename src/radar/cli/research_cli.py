"""``radar research`` — academic research radar (techniques)."""

from __future__ import annotations

from pathlib import Path

import typer

from radar.cli._shared import BUNDLED_ROOT, console


research_app = typer.Typer(help="Academic research radar (techniques).", no_args_is_help=True)

research_candidates_app = typer.Typer(
    help="Untracked paper-candidate discovery.", no_args_is_help=True
)
research_app.add_typer(research_candidates_app, name="candidates")


def _latest_technique_entries(root: Path):
    from radar.mcp_server.technique_queries import load_technique_entries

    entries = load_technique_entries(root)
    return entries or None


@research_app.command("scan")
def research_scan(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """Score seeded techniques against the radar's own catalogs + citations."""
    import asyncio
    import os

    import httpx

    from radar.research_radar.pipeline import momentum_for, run_research_scan
    from radar.research_radar.reports import build_technique_mover_lines, render_technique_report
    from radar.research_radar.seed import TechniqueSeedError, load_technique_seed
    from radar.storage.run_store import RunStore

    seed_path = root / "config" / "technique-seed.yaml"
    if not seed_path.exists():
        seed_path = BUNDLED_ROOT / "config" / "technique-seed.yaml"
    model_seed_path = root / "config" / "model-seed.yaml"
    if not model_seed_path.exists():
        model_seed_path = BUNDLED_ROOT / "config" / "model-seed.yaml"

    try:
        load_technique_seed(seed_path)
    except TechniqueSeedError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    run_store = RunStore(root / "data" / "runs")
    run_id = run_store.create_run()
    # Stamp the kind up front: a crashed scan must never masquerade as a tool run
    # (latest_tool_scan_meta filters on the absence of "kind").
    run_store.update_meta(run_id, {"kind": "research"})

    async def _run():
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            return await run_research_scan(
                seed_path=seed_path,
                config_path=root / "data" / "config.yaml",
                db_path=root / "data" / "radar.db",
                model_seed_path=model_seed_path,
                model_history_path=root / "data" / "model-history.jsonl",
                history_path=root / "data" / "technique-history.jsonl",
                client=client,
                contact_email=os.environ.get("RADAR_CONTACT_EMAIL"),
                run_id=run_id,
                metrics_log_path=root / "data" / "technique-metrics.jsonl",
            )

    entries, events = asyncio.run(_run())
    momentums = momentum_for(entries, root / "data" / "radar.db")
    report = render_technique_report(
        entries, build_technique_mover_lines(events, list(momentums.values())),
        "Academic Research Radar",
    )
    run_store.save_stage(run_id, "technique_cards", [e.model_dump(mode="json") for e in entries])
    run_store.save_report(run_id, report)
    run_store.update_meta(run_id, {"kind": "research", "technique_count": len(entries)})
    warned = sum(1 for e in entries if e.warnings)
    suffix = f" ({warned} with warnings)" if warned else ""
    console.print(f"Scanned {len(entries)} technique(s) → run {run_id}{suffix}")


@research_app.command("list")
def research_list(
    root: Path = typer.Option(Path("."), help="Project root."),
    ring: str = typer.Option("", help="Filter by ring: adopt|pilot|watch|avoid."),
    domain: str = typer.Option("", help="Filter by domain, e.g. inference."),
    category: str = typer.Option("", help="Filter by radar category."),
) -> None:
    """List techniques from the latest research scan."""
    entries = _latest_technique_entries(root)
    if entries is None:
        console.print(
            "[yellow]No research scan yet. Run [bold]radar research scan[/bold] first.[/yellow]"
        )
        return
    if ring:
        entries = [e for e in entries if e.ring and e.ring.value == ring.lower()]
    if domain:
        entries = [e for e in entries if e.domain.value == domain.lower()]
    if category:
        entries = [e for e in entries if e.category.value == category.lower()]
    console.print(f"{len(entries)} technique(s):")
    for e in entries:
        ring_label = e.ring.value if e.ring else "-"
        citations = str(e.citation_count) if e.citation_count is not None else "?"
        console.print(
            f"  {e.id:<26} {ring_label:<7} {e.domain.value:<18} "
            f"impls={len(e.resolved_implementations):<3} citations={citations}",
            highlight=False, soft_wrap=True,
        )


@research_app.command("show")
def research_show(
    technique_id: str = typer.Argument(..., help="Technique id, e.g. speculative-decoding."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """One technique: score breakdown, papers, implementations, ring history."""
    from radar.research_radar.history import load_technique_events

    entries = _latest_technique_entries(root)
    if entries is None:
        console.print(
            "[yellow]No research scan yet. Run [bold]radar research scan[/bold] first.[/yellow]"
        )
        return
    matches = [e for e in entries if e.id == technique_id]
    if not matches:
        console.print(f"[red]Unknown technique id:[/red] {technique_id}")
        raise typer.Exit(code=1)
    entry = matches[0]
    ring = entry.ring.value if entry.ring else "-"
    console.print(f"[bold]{entry.name}[/bold] ({entry.domain.value}) · ring: {ring}")
    if entry.score_breakdown is not None:
        b = entry.score_breakdown
        console.print(
            f"  breadth={b.implementation_breadth} maturity={b.implementation_maturity} "
            f"validation={b.validation} reproducibility={b.reproducibility} "
            f"momentum={b.momentum} onprem={b.onprem_impact} avg={b.average}"
        )
    for paper in entry.papers:
        console.print(f"  paper [{paper.role.value}] {paper.arxiv_id}: {paper.title}")
    for impl in entry.resolved_implementations:
        impl_ring = impl.ring.value if impl.ring else "unringed"
        console.print(f"  impl [{impl.kind.value}] {impl.ref} ({impl_ring})")
    for warning in entry.warnings:
        console.print(f"  [yellow]warning:[/yellow] {warning}")
    events = [e for e in load_technique_events(root / "data" / "technique-history.jsonl")
              if e.technique_id == technique_id]
    for event in events:
        console.print(
            f"  {event.observed_at.date()} {event.change_type.value} → {event.ring.value}"
        )


@research_app.command("discover")
def research_discover(
    root: Path = typer.Option(Path("."), help="Project root."),
    source: str = typer.Option("all", help="Candidate source: all | hf | arxiv."),
    days: int = typer.Option(7, help="arXiv sweep window in days."),
    min_upvotes: int = typer.Option(10, help="Minimum HF daily-papers upvotes."),
    limit: int = typer.Option(20, help="Maximum proposals to write."),
) -> None:
    """Propose technique candidates (HF daily papers + arXiv sweep, human-reviewed)."""
    import asyncio
    import os
    from datetime import UTC, datetime, timedelta

    import httpx

    from radar.discovery import (
        arxiv_technique_candidates,
        hf_technique_candidates,
        technique_candidate_velocity,
    )
    from radar.discovery.technique_proposals import write_technique_proposals
    from radar.research_radar.seed import TechniqueSeedError, load_technique_seed

    if source not in {"all", "hf", "arxiv"}:
        console.print(f"[red]Unknown --source: {source} (use all | hf | arxiv)[/red]")
        raise typer.Exit(code=1)
    seed_path = root / "config" / "technique-seed.yaml"
    if not seed_path.exists():
        seed_path = BUNDLED_ROOT / "config" / "technique-seed.yaml"
    try:
        seeds = load_technique_seed(seed_path)
    except TechniqueSeedError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    now = datetime.now(UTC)

    async def _run():
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            gathered = []
            if source in {"all", "hf"}:
                gathered.extend(await hf_technique_candidates.discover_technique_candidates(
                    seeds, client, min_upvotes=min_upvotes, limit=limit,
                ))
            if source in {"all", "arxiv"}:
                arxiv_found = await arxiv_technique_candidates.discover_arxiv_candidates(
                    seeds, client, since=now - timedelta(days=days), limit=limit,
                )
                seen = {p.arxiv_id for p in gathered}  # HF entries win duplicates
                gathered.extend(p for p in arxiv_found if p.arxiv_id not in seen)
            return await technique_candidate_velocity.enrich_proposals_with_velocity(
                gathered, client, now=now,
                contact_email=os.environ.get("RADAR_CONTACT_EMAIL"),
            )

    proposals = technique_candidate_velocity.rank_proposals(asyncio.run(_run()))[:limit]
    out_path = root / "data" / "proposed-technique-seeds.yaml"
    write_technique_proposals(out_path, proposals)
    if not proposals:
        console.print("No technique candidates found (or sources unavailable).")
        return
    console.print(
        f"{len(proposals)} technique candidate(s) → {out_path.relative_to(root)}"
    )


@research_candidates_app.command("scan")
def research_candidates_scan(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """Sweep untracked HF/arXiv paper candidates and append to the observation log."""
    import asyncio
    import os
    from datetime import UTC, datetime

    import httpx

    from radar.discovery.technique_candidate_sweep import sweep_technique_candidates
    from radar.research_radar.seed import TechniqueSeedError, load_technique_seed
    from radar.storage.technique_candidate_log import append_technique_candidates

    seed_path = root / "config" / "technique-seed.yaml"
    if not seed_path.exists():
        seed_path = BUNDLED_ROOT / "config" / "technique-seed.yaml"
    try:
        seeds = load_technique_seed(seed_path)
    except TechniqueSeedError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    now = datetime.now(UTC)

    async def _run():
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            return await sweep_technique_candidates(
                seeds, client, now, contact_email=os.environ.get("RADAR_CONTACT_EMAIL"))

    observations = asyncio.run(_run())
    out_path = root / "data" / "technique-candidate-observations.jsonl"
    append_technique_candidates(out_path, observations)
    console.print(f"Observed {len(observations)} untracked paper candidate(s) "
                  f"→ {out_path.relative_to(root)}")


@research_app.command("track-record")
def research_track_record(
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Paper-to-radar lag per technique (predictive hit-rate needs more history)."""
    import statistics

    from radar.research_radar.history import load_technique_events
    from radar.research_radar.track_record import build_track_record

    entries = _latest_technique_entries(root)
    if entries is None:
        console.print(
            "[yellow]No research scan yet. Run [bold]radar research scan[/bold] "
            "first.[/yellow]"
        )
        return
    events = load_technique_events(root / "data" / "technique-history.jsonl")
    rows = build_track_record(entries, events)
    console.print(f"{len(rows)} technique(s) with a flag date:")
    for row in rows:
        lag = f"{row.lag_days}d" if row.lag_days is not None else "?"
        console.print(
            f"  {row.technique_id:<32} paper={row.paper_published or '?':<10} "
            f"flagged={row.first_flagged}  lag={lag:<7} "
            f"{row.ring or '-':<6} impls={row.implementations}",
            highlight=False, soft_wrap=True,
        )
    lags = [r.lag_days for r in rows if r.lag_days is not None]
    if lags:
        console.print(f"Median paper→radar lag: {int(statistics.median(lags))} days")
    console.print(
        "Note: flag-to-implementation hit-rate needs accumulated implementation "
        "history and is not computed yet."
    )
