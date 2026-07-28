"""Command line interface for the adoption radar."""

from __future__ import annotations

import shutil
from datetime import UTC
from pathlib import Path
from typing import Any

import typer
import uvicorn
from rich.console import Console

from radar import __version__
from radar.constants import APP_NAME
from radar.init_project import initialize_project

# Imported at module level (not function-local, unlike this file's other
# commands) so tests can monkeypatch `radar.cli._verify_fetch_hf_model`
# directly — the seam `models verify` uses to stay offline in tests.
from radar.models_radar.collectors.huggingface import fetch_hf_model as _verify_fetch_hf_model
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
models_app = typer.Typer(help="Local-model radar (catalog + specs).", no_args_is_help=True)
app.add_typer(models_app, name="models")
research_app = typer.Typer(help="Academic research radar (techniques).", no_args_is_help=True)
app.add_typer(research_app, name="research")
trending_app = typer.Typer(help="Trending & newly-created repos radar.", no_args_is_help=True)
app.add_typer(trending_app, name="trending")
digest_app = typer.Typer(help="Weekly digest (page + cards + feeds + webhook).", no_args_is_help=True)
app.add_typer(digest_app, name="digest")
console = Console()

# `models verify`'s params_total drift check: some HF repos (NVIDIA's
# NVFP4/FP4-packed quant checkpoints) report a safetensors element count that
# is roughly half the real, published param total — a packing artifact, not
# real drift. Observed 2026-07-28 across three spec_verified seeds
# (hf-deepseek-v4-flash, hf-deepseek-v4-pro, hf-glm-5-2-nvfp4): ratios 1.80x,
# 1.86x, 1.98x. Below this ratio a mismatch is reported as DRIFT; at or above
# it, it's reported as a note and never trips --check — otherwise the weekly
# gate would go permanently red for a known, documented, deliberate
# seed/HF disagreement (a YAML comment records the correction, but comments
# aren't machine-parseable, so this ratio is the deterministic proxy).
_PACKED_QUANT_RATIO = 1.5


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
    publish_history: bool = typer.Option(
        False,
        "--publish-history",
        help="Append ring changes to the committed data/history.jsonl (CI only).",
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
        result = orchestrator.scan(
            days=days, profile=profile or None, publish_history=publish_history
        )
    except UnknownProfileError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if result.degraded:
        console.print(f"[red]DEGRADED:[/red] {result.degraded_reason}")
        console.print("No cards, history, or metrics were written.")
        raise typer.Exit(code=2)
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


@models_app.command("scan")
def models_scan(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """Collect model specs from HF + Ollama + seed; write a model_cards.json run."""
    import asyncio
    from datetime import UTC, datetime

    import httpx

    from radar.models_radar.entities import ModelEntry, ModelSeed
    from radar.models_radar.pipeline import persist_model_scan, score_entries
    from radar.models_radar.scan import run_model_scan
    from radar.models_radar.seed import load_model_seed
    from radar.models_radar.validate import (
        entry_advisories,
        seed_advisories,
        validate_entry,
        validate_seed,
    )
    from radar.storage.run_store import RunStore

    seed_path = root / "config" / "model-seed.yaml"
    if not seed_path.exists():
        # fall back to the packaged seed
        seed_path = Path(__file__).resolve().parents[2] / "config" / "model-seed.yaml"

    seeds = load_model_seed(seed_path)

    # Quarantine gate: absurd seeds (e.g. a mis-scraped params_total wildly off
    # the name's size token) never reach collection, scoring, or ranking.
    quarantined: dict[str, list[str]] = {}
    advisories: list[str] = []
    valid_seeds: list[ModelSeed] = []
    for seed in seeds:
        problems = validate_seed(seed)
        if problems:
            quarantined[seed.id] = problems
            continue
        advisories.extend(seed_advisories(seed))
        valid_seeds.append(seed)
    for seed_id, problems in quarantined.items():
        console.print(f"[red]QUARANTINED {seed_id}:[/red] {'; '.join(problems)}")
    for advisory in advisories:
        console.print(f"[yellow]note:[/yellow] {advisory}")

    async def _run():
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            return await run_model_scan(
                valid_seeds, client, retrieved_at=datetime.now(UTC).date().isoformat()
            )

    entries = asyncio.run(_run())

    # Post-assembly quarantine gate: an entry whose params are known but whose
    # specs never resolve to a usable minimum-viable memory number (e.g. no HF
    # data, no ollama, empty quants) is excluded from scoring/persistence, but
    # stays visible in the model_cards stage — its problems folded into
    # warnings — so operators can see exactly why. Mirrors the seed gate
    # above, one stage later.
    entry_quarantined: dict[str, list[str]] = {}
    entry_advisory_notes: list[str] = []
    valid_entries: list[ModelEntry] = []
    kept_entries: list[ModelEntry] = []
    for entry in entries:
        problems = validate_entry(entry)
        if problems:
            entry_quarantined[entry.id] = problems
            kept_entries.append(
                entry.model_copy(update={"warnings": [*entry.warnings, *problems]})
            )
            continue
        entry_advisory_notes.extend(entry_advisories(entry))
        valid_entries.append(entry)
        kept_entries.append(entry)
    for entry_id, problems in entry_quarantined.items():
        console.print(f"[red]QUARANTINED {entry_id}:[/red] {'; '.join(problems)}")
    for advisory in entry_advisory_notes:
        console.print(f"[yellow]note:[/yellow] {advisory}")

    scored_entries = score_entries(valid_entries)
    scored_by_id = {e.id: e for e in scored_entries}
    final_entries = [scored_by_id.get(e.id, e) for e in kept_entries]

    run_store = RunStore(root / "data" / "runs")
    run_id = run_store.create_run()
    # Stamp the kind up front: a crashed scan must never masquerade as a tool run
    # (latest_tool_scan_meta filters on the absence of "kind").
    run_store.update_meta(run_id, {"kind": "models"})
    all_warnings = [
        *(p for ps in quarantined.values() for p in ps), *advisories,
        *(p for ps in entry_quarantined.values() for p in ps), *entry_advisory_notes,
    ]
    if all_warnings:
        run_store.update_meta(run_id, {"model_validation_warnings": all_warnings})
    observed_at = datetime.now(UTC)
    persist_model_scan(
        scored_entries, run_id, observed_at,
        root / "data" / "radar.db", root / "data" / "model-history.jsonl",
        metrics_log_path=root / "data" / "model-metrics.jsonl",
    )
    run_store.save_stage(
        run_id, "model_cards", [m.model_dump(mode="json") for m in final_entries]
    )
    run_store.update_meta(run_id, {"kind": "models", "model_count": len(final_entries)})
    console.print(f"Scanned {len(final_entries)} models → run {run_id}")


@models_app.command("verify")
def models_verify(
    root: Path = typer.Option(Path("."), help="Project root."),
    check: bool = typer.Option(
        False, "--check", help="Exit 1 on drift in a spec_verified seed."
    ),
) -> None:
    """Diff seed spec numbers against fresh HF data. Never modifies seeds."""
    import asyncio

    import httpx

    from radar.models_radar.collectors.huggingface import HFModelData
    from radar.models_radar.entities import ArchitectureSpec
    from radar.models_radar.seed import load_model_seed

    seed_path = root / "config" / "model-seed.yaml"
    if not seed_path.exists():
        # fall back to the packaged seed
        seed_path = Path(__file__).resolve().parents[2] / "config" / "model-seed.yaml"

    seeds = [s for s in load_model_seed(seed_path) if s.enabled and s.hf_repo]

    async def _collect() -> dict[str, HFModelData | None]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            return {
                s.id: await _verify_fetch_hf_model(s.hf_repo, client)  # type: ignore[arg-type]
                for s in seeds
            }

    fetched = asyncio.run(_collect())
    drift_verified = 0
    drift_total = 0
    for seed in seeds:
        hf = fetched.get(seed.id)
        if hf is None:
            console.print(f"[yellow]skip {seed.id}: HF unreachable[/yellow]")
            continue
        rows: list[tuple[str, object, object]] = []

        seed_pt, hf_pt = seed.params_total, hf.params_total
        if seed_pt is not None and hf_pt is not None and seed_pt != hf_pt:
            low, high = sorted((seed_pt, hf_pt))
            ratio = (high / low) if low else float("inf")
            if ratio > _PACKED_QUANT_RATIO:
                # Known artifact (see _PACKED_QUANT_RATIO above): report it,
                # but never as DRIFT — the seed's total is the deliberately
                # corrected, cited value.
                console.print(
                    f"[yellow]note {seed.id}: params_total differs by {ratio:.2f}x "
                    "(packed-quant artifact, seed carries published total)[/yellow]"
                )
            else:
                rows.append(("params_total", seed_pt, hf_pt))

        seed_ctx, hf_ctx = seed.context_length, hf.context_length
        if seed_ctx is not None and hf_ctx is not None and seed_ctx != hf_ctx:
            rows.append(("context_length", seed_ctx, hf_ctx))

        if seed.architecture is not None and hf.architecture is not None:
            for field in ArchitectureSpec.model_fields:
                if field == "attention_kind":
                    continue  # derived, not a number to drift-check
                seed_value = getattr(seed.architecture, field)
                hf_value = getattr(hf.architecture, field)
                if seed_value is not None and hf_value is not None and seed_value != hf_value:
                    rows.append((f"architecture.{field}", seed_value, hf_value))

        for field, seed_value, hf_value in rows:
            drift_total += 1
            if seed.spec_verified:
                drift_verified += 1
            console.print(
                f"[red]DRIFT {seed.id}.{field}:[/red] seed={seed_value} hf={hf_value}"
            )

    if drift_total == 0:
        console.print(f"OK: {len(seeds)} seeds verified, no drift")
    if check and drift_verified:
        raise typer.Exit(code=1)


candidates_app = typer.Typer(help="Untracked model-candidate discovery.", no_args_is_help=True)
models_app.add_typer(candidates_app, name="candidates")


@candidates_app.command("scan")
def candidates_scan(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """Sweep untracked HF-trending models and append to the candidate observation log."""
    import asyncio
    from datetime import UTC, datetime

    import httpx

    from radar.discovery.model_candidate_sweep import sweep_model_candidates
    from radar.models_radar.seed import load_model_seed
    from radar.storage.model_candidate_log import append_model_candidates

    seed_path = root / "config" / "model-seed.yaml"
    if not seed_path.exists():
        seed_path = Path(__file__).resolve().parents[2] / "config" / "model-seed.yaml"
    seeds = load_model_seed(seed_path)
    now = datetime.now(UTC)

    async def _run():
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            return await sweep_model_candidates(seeds, client, now)

    observations = asyncio.run(_run())
    out_path = root / "data" / "model-candidate-observations.jsonl"
    append_model_candidates(out_path, observations)
    console.print(f"Observed {len(observations)} untracked model candidate(s) "
                  f"→ {out_path.relative_to(root)}")


@models_app.command("discover")
def models_discover(
    min_downloads: int = typer.Option(10000, help="Minimum HF downloads for a candidate."),
    limit: int = typer.Option(50, help="Max candidates to fetch/propose."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Find trending HF models and write proposals for review (never auto-adds)."""
    import asyncio

    import httpx

    from radar.discovery.hf_trending_models import discover_trending_models
    from radar.discovery.model_proposals import write_model_proposals
    from radar.models_radar.seed import load_model_seed

    seed_path = root / "config" / "model-seed.yaml"
    if not seed_path.exists():
        seed_path = Path(__file__).resolve().parents[2] / "config" / "model-seed.yaml"
    seeds = load_model_seed(seed_path)

    async def _run():
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            return await discover_trending_models(
                seeds, client, min_downloads=min_downloads, limit=limit
            )

    proposals = asyncio.run(_run())
    out_path = root / "data" / "proposed-model-seeds.yaml"
    write_model_proposals(out_path, proposals)
    console.print(f"Found {len(proposals)} model candidate(s) → {out_path}")
    for p in proposals[:15]:
        console.print(
            f"  {p.downloads:>9,}↓  {p.model_id:<32} {p.family:<14} {p.hf_repo}",
            highlight=False,
        )


@models_app.command("promote")
def models_promote(
    min_downloads: int = typer.Option(100000, help="Minimum HF downloads to promote."),
    limit: int = typer.Option(5, help="Max new models to add per run."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print what would be added; do not write."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Promote high-quality proposals from data/proposed-model-seeds.yaml into config/model-seed.yaml."""
    import asyncio
    from datetime import UTC, datetime

    import httpx

    from radar.discovery.model_promotion import (
        build_seed,
        promotable_candidates,
        seed_to_yaml_block,
    )
    from radar.discovery.model_proposals import load_model_proposals
    from radar.models_radar.collectors.huggingface import fetch_hf_model
    from radar.models_radar.entities import ModelSeed
    from radar.models_radar.seed import ModelSeedError, load_model_seed
    from radar.storage.model_candidate_log import load_model_candidates

    seed_path = root / "config" / "model-seed.yaml"
    if not seed_path.exists():
        seed_path = Path(__file__).resolve().parents[2] / "config" / "model-seed.yaml"
    seeds = load_model_seed(seed_path)

    seeded_repos = {s.hf_repo.lower() for s in seeds if s.hf_repo}
    existing_ids = {s.id for s in seeds}

    proposals_path = root / "data" / "proposed-model-seeds.yaml"
    proposals = load_model_proposals(proposals_path)
    if not proposals:
        console.print(f"No proposals found at {proposals_path}.")
        return

    observations = load_model_candidates(root / "data" / "model-candidate-observations.jsonl")
    now = datetime.now(UTC)
    candidates = promotable_candidates(
        proposals, observations, min_downloads=min_downloads,
        seeded_repos=seeded_repos, now=now)

    async def _run() -> list[ModelSeed]:
        _collected: list[ModelSeed] = []
        _existing = set(existing_ids)
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            _client: Any = client
            for p in candidates:
                if len(_collected) >= limit:
                    break
                hf = await fetch_hf_model(p.hf_repo, _client)
                if hf is None:
                    console.print(f"  [dim]skip {p.hf_repo}: HF fetch failed[/dim]")
                    continue
                if hf.params_total is None:
                    console.print(f"  [dim]skip {p.hf_repo}: no params_total from HF[/dim]")
                    continue
                seed = build_seed(p, hf, existing_ids=_existing)
                if seed is None:
                    continue
                _existing = _existing | {seed.id}
                _collected.append(seed)
        return _collected

    collected: list[ModelSeed] = asyncio.run(_run())

    if not collected:
        console.print("No new models qualified.")
        return

    if dry_run:
        from rich.table import Table

        table = Table(title="Would promote (dry run)")
        table.add_column("id")
        table.add_column("family")
        table.add_column("params_total")
        table.add_column("hf_repo")
        for s in collected:
            table.add_row(
                s.id,
                s.family,
                str(s.params_total) if s.params_total is not None else "",
                s.hf_repo or "",
            )
        console.print(table)
        return

    old_text = seed_path.read_text(encoding="utf-8")
    # Separate each appended entry with a blank line, matching the hand-authored style.
    blocks = "".join("\n" + seed_to_yaml_block(s).strip("\n") + "\n" for s in collected)
    new_text = old_text.rstrip("\n") + "\n" + blocks

    tmp = seed_path.with_suffix(".promote.tmp")
    tmp.write_text(new_text, encoding="utf-8")

    try:
        loaded = load_model_seed(tmp)
    except ModelSeedError as exc:
        tmp.unlink(missing_ok=True)
        console.print(f"[red]Validation failed: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    loaded_ids = [s.id for s in loaded]
    if len(loaded_ids) != len(set(loaded_ids)):
        tmp.unlink(missing_ok=True)
        console.print("[red]Duplicate IDs detected after promotion; aborting.[/red]")
        raise typer.Exit(code=1)

    tmp.replace(seed_path)
    for s in collected:
        console.print(f"  [green]added[/green] {s.id}  ({s.hf_repo})")
    console.print(f"Promoted {len(collected)} model(s) → {seed_path}")


@models_app.command("devices")
def models_devices() -> None:
    """List built-in device presets for the fit check."""
    from radar.models_radar.devices import DEVICE_PRESETS, usable_memory_gb
    for key, d in DEVICE_PRESETS.items():
        console.print(f"  {key:<20} {d.name:<28} ~{usable_memory_gb(d):>6.1f} GB usable",
                      highlight=False)


@models_app.command("fit")
def models_fit(
    device: str = typer.Option("", help="Preset id (see `radar models devices`)."),
    memory: float = typer.Option(0.0, help="Custom: total memory GB (with --kind)."),
    kind: str = typer.Option("gpu", help="Custom device kind: gpu|apple|cpu."),
    gpus: int = typer.Option(1, help="Custom: number of GPUs."),
    context: int = typer.Option(4096, help="Context length (tokens) for the estimate."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Show which tracked models fit a device, and at which quant."""
    from radar.mcp_server.model_queries import _latest_model_cards
    from radar.models_radar.device_fit import fit_report
    from radar.models_radar.devices import DeviceError, resolve_device
    from radar.models_radar.entities import ModelEntry

    try:
        spec: str | dict = device or {"kind": kind, "total_memory_gb": memory, "gpu_count": gpus}
        if not device and memory <= 0:
            console.print("[red]Provide --device <preset> or --memory <GB>.[/red]")
            raise typer.Exit(code=1)
        dev = resolve_device(spec)
    except DeviceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    entries = [ModelEntry.model_validate(c) for c in _latest_model_cards(root)]
    if not entries:
        console.print("[yellow]No model scan yet. Run [bold]radar models scan[/bold] first.[/yellow]")
        return
    from radar.models_radar.devices import usable_memory_gb
    console.print(f"{dev.name} — ~{usable_memory_gb(dev):.1f} GB usable @ {context} ctx:")
    for f in fit_report(entries, dev, context):
        q = f.best_quant_format or "-"
        console.print(f"  {f.model_id:<28} {f.verdict:<15} {q}", highlight=False)


@models_app.command("list")
def models_list(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """List models from the latest model scan."""
    import json as _json
    from datetime import UTC, datetime

    from radar.models_radar.entities import ModelEntry as _ME
    from radar.models_radar.pipeline import momentum_for
    from radar.storage.run_store import RunStore

    run_store = RunStore(root / "data" / "runs")
    model_run = run_store.latest_run_of_kind("models")
    if model_run is None:
        console.print("[yellow]No model scan yet. Run [bold]radar models scan[/bold] first.[/yellow]")
        return
    cards_path = run_store._run_dir(model_run) / "model_cards.json"
    entries = _json.loads(cards_path.read_text(encoding="utf-8"))
    console.print(f"{len(entries)} models (run {model_run}):")
    parsed = [_ME.model_validate(m) for m in entries]
    moms = momentum_for(parsed, root / "data" / "radar.db",
                        root / "data" / "model-history.jsonl", datetime.now(UTC))
    _ARROW = {"rising": "↑", "falling": "↓", "steady": "→"}
    for m in parsed:
        quants = m.quants
        mems = [q.est_memory_gb_4k for q in quants
                if q.est_memory_gb_4k and q.bits_per_weight >= 4.0]
        min_mem = f"{min(mems):.1f}GB" if mems else "?"
        arrow = _ARROW.get(moms[m.id].direction, "")
        ring = m.ring.value if m.ring else "-"
        console.print(
            f"  {m.id:<28} {ring:<7} {m.hardware_tier.value:<16} "
            f"min~{min_mem:<9} {arrow} {m.family}",
            highlight=False,
        )


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
        seed_path = Path(__file__).resolve().parents[2] / "config" / "technique-seed.yaml"
    model_seed_path = root / "config" / "model-seed.yaml"
    if not model_seed_path.exists():
        model_seed_path = Path(__file__).resolve().parents[2] / "config" / "model-seed.yaml"

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
        seed_path = Path(__file__).resolve().parents[2] / "config" / "technique-seed.yaml"
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


research_candidates_app = typer.Typer(help="Untracked paper-candidate discovery.", no_args_is_help=True)
research_app.add_typer(research_candidates_app, name="candidates")


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
        seed_path = Path(__file__).resolve().parents[2] / "config" / "technique-seed.yaml"
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


def _latest_technique_entries(root: Path):
    from radar.mcp_server.technique_queries import load_technique_entries

    entries = load_technique_entries(root)
    return entries or None


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


@digest_app.command("generate")
def digest_generate(
    root: Path = typer.Option(Path("."), help="Project root."),
    base_url: str = typer.Option(
        "",
        help=(
            "Absolute site URL (e.g. https://user.github.io/repo) used to make the "
            "digest page and Atom/RSS feed URLs absolute. Defaults to relative filenames."
        ),
    ),
    top_n: int = typer.Option(5, help="Max trending entries per lane in the digest."),
) -> None:
    """Assemble this week's digest: page + cards + feeds + (optional) webhook."""
    import asyncio
    import contextlib
    from datetime import UTC, datetime

    import httpx
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    from radar.mcp_server.trending_queries import load_trending_entries
    from radar.models import NotifyConfig
    from radar.models_radar.history import load_model_events
    from radar.notify import webhook
    from radar.reports.digest import build_digest
    from radar.reports.digest_feeds import render_digest_atom, render_digest_rss
    from radar.research_radar.history import load_technique_events
    from radar.storage.autopilot_log import load_autopilot
    from radar.storage.config import ConfigError, load_config
    from radar.storage.digest_log import DigestLogEntry, append_digest, load_digests
    from radar.storage.history_log import load_events
    from radar.web.cards import write_cards
    from radar.web.static_site import _TEMPLATE_DIR

    if base_url and not base_url.startswith(("http://", "https://")):
        raise typer.BadParameter(
            "--base-url must be an absolute http(s) URL, e.g. https://user.github.io/repo",
            param_hint="--base-url",
        )

    now = datetime.now(UTC)
    trending = load_trending_entries(root, now)
    autopilot = load_autopilot(root / "data" / "autopilot-log.jsonl")
    tool_events = load_events(root / "data" / "history.jsonl")
    model_events = load_model_events(root / "data" / "model-history.jsonl")
    technique_events = load_technique_events(root / "data" / "technique-history.jsonl")

    digest = build_digest(
        now, trending, autopilot, tool_events, model_events, technique_events, top_n=top_n,
    )

    out_dir = root / "digests"
    out_dir.mkdir(parents=True, exist_ok=True)
    base = base_url.rstrip("/") if base_url else ""

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=select_autoescape(["html"])
    )
    env.globals["asset_base"] = "../"
    page_name = f"digest_{digest.label}.html"
    (out_dir / page_name).write_text(
        env.get_template("digest.html").render(digest=digest), encoding="utf-8"
    )

    cards = write_cards(digest, out_dir / "cards")

    log_path = root / "data" / "digest-log.jsonl"
    existing_labels = {e.label for e in load_digests(log_path)}
    label_is_new = digest.label not in existing_labels
    page_url = f"{base}/digests/{page_name}" if base else f"digests/{page_name}"
    if label_is_new:
        append_digest(log_path, [DigestLogEntry(
            label=digest.label, generated_at=digest.generated_at,
            url=page_url, summary=digest.summary_line,
        )])
    all_entries = load_digests(log_path)

    site_title = "On-Prem AI Adoption Radar — Weekly Digest"
    atom_url = f"{base}/digests/digest.xml" if base else "digests/digest.xml"
    rss_url = f"{base}/digests/digest-rss.xml" if base else "digests/digest-rss.xml"
    (out_dir / "digest.xml").write_text(
        render_digest_atom(all_entries, site_title, atom_url), encoding="utf-8"
    )
    (out_dir / "digest-rss.xml").write_text(
        render_digest_rss(all_entries, site_title, rss_url), encoding="utf-8"
    )

    # Webhook is best-effort: a missing/invalid config or a down endpoint must
    # never fail digest generation.
    notify_config = NotifyConfig()
    with contextlib.suppress(ConfigError):
        notify_config = load_config(root / "data" / "config.yaml").notify

    async def _notify() -> bool:
        async with httpx.AsyncClient(
            timeout=float(notify_config.timeout_seconds)
        ) as client:
            return await webhook.send_digest_notification(notify_config, digest, client)

    # Fire the webhook only for a newly-logged week — a manual re-run of the same
    # ISO week rewrites artifacts but must not re-ping subscribers.
    if label_is_new:
        try:
            asyncio.run(_notify())
        except Exception as exc:
            console.print(f"[yellow]Digest webhook failed: {exc}[/yellow]")

    console.print(
        f"Digest {digest.label}: {out_dir.relative_to(root) / page_name} · "
        f"{len(cards)} card(s) · {len(all_entries)} digest(s) in log"
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
    from radar.discovery.hf_papers import discover_from_hf_papers
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
            trending = await discover_trending(
                config.sources, client, categories=categories,
                min_stars=min_stars, since_days=since_days, headers=_headers(),
            )
            hf = await discover_from_hf_papers(
                config.sources, client, min_stars=min_stars, headers=_headers(),
            )
            merged: dict[str, Any] = {p.url: p for p in hf}
            for proposal in trending:  # trending overrides HF on URL collision
                merged[proposal.url] = proposal
            return sorted(merged.values(), key=lambda p: p.stars, reverse=True)

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


history_app = typer.Typer(help="Project ring timeline.", invoke_without_command=True)
app.add_typer(history_app, name="history")


@history_app.callback()
def history(
    ctx: typer.Context,
    project: str = typer.Option("", help="Limit to a single project (optional)."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Print the cumulative per-project observation history."""
    if ctx.invoked_subcommand is not None:
        return
    from radar.reports.history import render_history_report
    from radar.storage.history_store import HistoryStore

    store = HistoryStore(root / "data" / "radar.db")
    store.initialize()
    # all_summaries(), not summaries(): a project entirely corrected away
    # must still show its raw timeline here.
    summaries = store.all_summaries()
    if project:
        summaries = [s for s in summaries if s.project == project]
    events = {s.project: store.history_for(s.project) for s in summaries}
    console.print(render_history_report(summaries, events, "Adoption History"))


@history_app.command("repair")
def history_repair(
    root: Path = typer.Option(Path("."), help="Project root."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show corrections, write nothing."),
) -> None:
    """Neutralize ring changes from collection-outage runs (append-only)."""
    import sqlite3
    from datetime import UTC, datetime

    from radar.orchestrator import RadarOrchestrator
    from radar.storage.history_log import append_events, load_events
    from radar.storage.history_repair import build_corrections, outage_run_ids

    orchestrator = RadarOrchestrator(root)
    orchestrator.history.initialize()
    # Legacy backfill only: if the log is missing/empty but the DB has real
    # history, this regenerates the log from the DB (see docs/persistence.md).
    # It does NOT make the DB authoritative going forward — the log below is.
    orchestrator.reconcile_history()
    # The durable JSONL log is truth, not the SQLite projection: both the
    # event stream corrections are derived from AND the "already corrected"
    # idempotence set must come from `load_events`, never from
    # `orchestrator.history.all_events()`. The DB can get ahead of the log
    # (e.g. a `corrected` marker written to the DB whose log append never
    # landed) — reading the DB there would make that drift permanently
    # unhealable, which is exactly the 2026-07-27 incident this guards against.
    events = load_events(orchestrator.history_log)
    try:
        outages = outage_run_ids(root / "data" / "radar.db")
    except sqlite3.OperationalError:
        # Fresh root: no scan has ever run, so source_health doesn't exist yet.
        console.print("No outage evidence recorded.")
        return
    corrections = build_corrections(events, outages, datetime.now(UTC))
    console.print(f"Outage runs detected: {len(outages)}")
    console.print(f"Corrections to append: {len(corrections)}")
    for c in corrections:
        previous_ring = c.previous_ring.value if c.previous_ring else "?"
        console.print(f"  {c.project}: {previous_ring} -> {c.ring.value} ({c.corrects_run_id})")
    if dry_run or not corrections:
        return
    # The log append is unconditional (it's the log's own idempotence check
    # above that decided these corrections are new); the DB insert is
    # deduped separately via import_events's natural key so a correction
    # already present in the DB (again, today's exact drift) isn't
    # double-inserted there.
    orchestrator.history.import_events(corrections)
    append_events(orchestrator.history_log, corrections)
    console.print(f"Appended {len(corrections)} corrected events.")


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
    # seen_projects(), not summaries(): calibration must see raw history for
    # every project, including one entirely corrected away.
    events = [e for p in history.seen_projects() for e in history.history_for(p)]

    report = build_calibration_report(scored, ring_by_project, history_events=events)
    console.print(render_calibration_markdown(report))
    # Quality gate: fail only on collapse (one ring, or >80% in a single ring),
    # which means scoring stopped discriminating — a real regression.
    if check and not report.discriminates:
        console.print(
            "[red]Quality gate failed:[/red] rings do not discriminate."
        )
        raise typer.Exit(code=1)


@app.command("scan-health")
def scan_health_cmd(
    root: Path = typer.Option(Path("."), help="Project root."),
    check: bool = typer.Option(False, "--check", help="Exit non-zero if unhealthy."),
    min_signals: int = typer.Option(20, help="Minimum raw signals for a publishable run."),
) -> None:
    """Health of the latest main scan run (the publish gate reads this)."""
    from radar.storage.run_store import RunStore

    run_store = RunStore(root / "data" / "runs")
    run_id = run_store.latest_run_of_kind(None)
    if run_id is None:
        console.print("[red]No main scan run found.[/red]")
        raise typer.Exit(code=1 if check else 0)

    meta = run_store.read_meta(run_id)
    problems: list[str] = []
    if meta.get("degraded"):
        problems.append(f"run is degraded: {meta.get('degraded_reason', 'unknown reason')}")
    try:
        raw = run_store.load_stage(run_id, "raw_signals")
    except FileNotFoundError:
        raw = []
    if len(raw) < min_signals:
        problems.append(f"only {len(raw)} raw signals (< {min_signals})")
    if problems:
        for problem in problems:
            console.print(f"[red]UNHEALTHY:[/red] {problem}")
        raise typer.Exit(code=1 if check else 0)
    console.print(f"OK: {run_id} — {len(raw)} raw signals, not degraded")


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


EXPORT_RESEARCH_STALE_DAYS = 2


def _research_snapshot_status(
    technique_entries: list[Any], run_store: Any, now: Any,
) -> tuple[bool, str]:
    """Warn-only staleness check for the export command.

    Returns ``(is_stale, latest_research_run_id)``. Export always renders the
    latest research run's ``technique_cards.json`` snapshot as-is (see
    ``load_technique_entries``); a missing, empty, or stale snapshot would
    otherwise silently publish outdated technique pages, so this warns
    instead of blocking the daily publish.
    """
    from datetime import datetime

    latest_run_id = "none"
    stamp: str | None = None
    try:
        latest = run_store.latest_run_of_kind("research")
        if latest is not None:
            latest_run_id = latest
            meta = run_store.read_meta(latest)
            stamp = meta.get("updated_at") or meta.get("created_at")
    except Exception:
        return True, latest_run_id

    if not technique_entries or not stamp:
        return True, latest_run_id

    try:
        run_time = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return True, latest_run_id
    if run_time.tzinfo is None:
        run_time = run_time.replace(tzinfo=UTC)

    age_days = (now - run_time).days
    return age_days >= EXPORT_RESEARCH_STALE_DAYS, latest_run_id


@app.command()
def export(
    out: Path = typer.Option(Path("_site"), help="Output directory for static HTML."),
    root: Path = typer.Option(Path("."), help="Project root."),
    base_url: str = typer.Option(
        "",
        help=(
            "Absolute site URL (e.g. https://user.github.io/repo) used to make the "
            "Atom/RSS feed self/link URLs absolute. Defaults to relative filenames."
        ),
    ),
) -> None:
    """Render a static HTML snapshot (for GitHub Pages) from the latest scan."""
    from datetime import datetime

    # Validate at the boundary: a non-empty base URL must be absolute http(s),
    # otherwise the feed self/link URLs would be silently malformed.
    if base_url and not base_url.startswith(("http://", "https://")):
        raise typer.BadParameter(
            "--base-url must be an absolute http(s) URL, e.g. https://user.github.io/repo",
            param_hint="--base-url",
        )

    from radar.mcp_server.model_queries import _latest_model_cards
    from radar.models_radar.entities import ModelEntry
    from radar.models_radar.history import load_model_events
    from radar.storage.config import ConfigError, load_config
    from radar.storage.digest_log import load_digests
    from radar.storage.history_store import HistoryStore
    from radar.storage.metrics_store import MetricsStore
    from radar.storage.source_health_store import SourceHealthStore
    from radar.web.scan_health import latest_tool_scan_meta
    from radar.web.source_health import summarize_source_health
    from radar.web.static_site import render_static_site

    orchestrator = RadarOrchestrator(root)
    cards = orchestrator.latest_cards()

    history = HistoryStore(root / "data" / "radar.db")
    history.initialize()
    # all_summaries(), not summaries(): a project entirely corrected away
    # must still show its raw timeline and feed entries here.
    timelines = [
        {"summary": s, "events": history.history_for(s.project)}
        for s in sorted(history.all_summaries(), key=lambda s: s.last_change_at, reverse=True)
    ]

    metrics = MetricsStore(root / "data" / "radar.db")
    metrics.initialize()
    metrics_by_project = {c.project: metrics.history_for(c.project) for c in cards}

    latest_scan_meta = latest_tool_scan_meta(orchestrator.run_store)

    # Source-health is best-effort: a missing config (e.g. a manual export
    # before init) should not block publishing the snapshot.
    source_health_view = None
    try:
        config = load_config(root / "data" / "config.yaml")
    except ConfigError:
        config = None
    if config is not None:
        source_health = SourceHealthStore(root / "data" / "radar.db")
        source_health.initialize()
        source_health_view = summarize_source_health(
            source_health.stale_source_ids(),
            source_health.latest_counts(),
            config.sources,
        )

    # Model entries + events (optional: only present after a `radar models scan`).
    model_entries = [ModelEntry.model_validate(c) for c in _latest_model_cards(root)]
    model_events = load_model_events(root / "data" / "model-history.jsonl")

    # Copy model-history.jsonl into the site so it's available as a download.
    model_history_src = root / "data" / "model-history.jsonl"
    out.mkdir(parents=True, exist_ok=True)
    if model_history_src.exists():
        shutil.copy2(model_history_src, out / "model-history.jsonl")

    # Technique entries + events (optional: only present after a `radar research scan`).
    from radar.mcp_server.technique_queries import load_technique_entries
    from radar.research_radar.entities import ImplKind
    from radar.research_radar.history import load_technique_events as _load_tech_events

    technique_entries = load_technique_entries(root)
    technique_events = _load_tech_events(root / "data" / "technique-history.jsonl")

    research_stale, latest_research_run_id = _research_snapshot_status(
        technique_entries, orchestrator.run_store, datetime.now(UTC),
    )
    if research_stale:
        console.print(
            "[yellow]⚠ research data is stale/missing "
            f"(latest research run: {latest_research_run_id}); "
            "run `radar research scan` before export[/yellow]"
        )

    technique_history_src = root / "data" / "technique-history.jsonl"
    if technique_history_src.exists():
        shutil.copy2(technique_history_src, out / "technique-history.jsonl")

    # Trending observations (optional: only present after `radar trending scan`).
    from radar.storage.trending_observations_log import load_observations as _load_trending_obs

    trending_observations = _load_trending_obs(root / "data" / "trending-observations.jsonl")

    # Pedigree maps (optional: only meaningful once technique entries exist) —
    # drive the "Research techniques" section on project + model static pages.
    from radar.research_radar.pedigree import (
        TechniquePedigree,
        build_pedigree_index,
        pedigree_for_refs,
    )
    from radar.web.slugs import build_slug_map

    pedigree_by_project: dict[str, list[TechniquePedigree]] = {}
    pedigree_by_model: dict[str, list[TechniquePedigree]] = {}
    technique_hrefs: dict[str, str] = {}
    impl_hrefs: dict[str, str] = {}
    if technique_entries:
        technique_slugs = build_slug_map([t.id for t in technique_entries])
        technique_hrefs = {tid: f"technique_{slug}.html" for tid, slug in technique_slugs.items()}
        pedigree_index = build_pedigree_index(technique_entries)
        try:
            export_config = load_config(root / "data" / "config.yaml")
            sources = export_config.sources
        except Exception:
            sources = []
        ids_by_project: dict[str, list[str]] = {}
        for source in sources:
            ids_by_project.setdefault(source.project, []).append(source.id)
        pedigree_by_project = {
            project: items for project, ids in ids_by_project.items()
            if (items := pedigree_for_refs(pedigree_index.by_tool_ref, ids))
        }
        pedigree_by_model = {
            ref: items for ref in pedigree_index.by_model_ref
            if (items := pedigree_for_refs(pedigree_index.by_model_ref, [ref]))
        }

        # Implementation hrefs (optional): link each technique's implementations
        # back to the project/model page, but only when that page exists in
        # this export (a project card and/or a model entry with a real slug).
        project_by_id = {s.id: s.project for s in sources}
        card_slugs = build_slug_map([c.project for c in cards])
        model_slugs = build_slug_map([m.id for m in model_entries]) if model_entries else {}
        for technique in technique_entries:
            for impl in technique.resolved_implementations:
                if impl.ref in impl_hrefs:
                    continue
                if impl.kind == ImplKind.TOOL:
                    project = project_by_id.get(impl.ref)
                    if project in card_slugs:
                        impl_hrefs[impl.ref] = f"project_{card_slugs[project]}.html"
                elif impl.ref in model_slugs:
                    impl_hrefs[impl.ref] = f"model_{model_slugs[impl.ref]}.html"

    # Weekly digests (optional): only present after `radar digest generate`.
    digests = load_digests(root / "data" / "digest-log.jsonl")
    latest_digest = max(digests, key=lambda d: d.generated_at) if digests else None

    # Trending-hub sections (optional): rising/new-this-week models + techniques
    # for the trending page's "Trending Models"/"Trending Techniques" sections
    # and the index strip's top-model/top-technique highlights.
    from radar.web.hub_sections import load_hub_sections

    generated_at = datetime.now(UTC)
    _model_hub, _technique_hub = load_hub_sections(root, generated_at)

    # Emerging models (optional): untracked Hugging Face repos with rising
    # download velocity, shown on trending.html under "Emerging — not yet
    # tracked". Guarded gateway: excludes already-seeded/promoted repos, caps
    # the list, and degrades to [] on any failure (corrupt store, bad seed, …).
    from radar.discovery.model_candidate_detect import load_emerging_candidates

    _model_candidates = load_emerging_candidates(root, generated_at)

    # Emerging techniques (optional): untracked arXiv papers with rising
    # upvote velocity, shown on trending.html under "Emerging — not yet
    # tracked" (mirror of the model candidates above).
    from radar.discovery.technique_candidate_detect import load_emerging_techniques

    _technique_candidates = load_emerging_techniques(root, generated_at)

    index = render_static_site(
        cards,
        out,
        generated_at,
        timelines=timelines,
        self_base_url=base_url,
        metrics_by_project=metrics_by_project,
        latest_scan_meta=latest_scan_meta,
        history_jsonl=root / "data" / "history.jsonl",
        source_health=source_health_view,
        model_entries=model_entries or None,
        model_events=model_events or None,
        technique_entries=technique_entries or None,
        technique_events=technique_events or None,
        trending_observations=trending_observations or None,
        pedigree_by_project=pedigree_by_project or None,
        pedigree_by_model=pedigree_by_model or None,
        technique_hrefs=technique_hrefs or None,
        impl_hrefs=impl_hrefs or None,
        digest_dir=root / "digests",
        latest_digest=latest_digest,
        model_hub=_model_hub or None,
        technique_hub=_technique_hub or None,
        top_model=next((r for r in _model_hub if not r.is_new), None),
        top_technique=next((r for r in _technique_hub if not r.is_new), None),
        model_candidates=_model_candidates or None,
        technique_candidates=_technique_candidates or None,
        card_staleness=orchestrator.database.card_staleness_note(),
    )
    console.print(
        f"Wrote {index.parent}/ (index, compare, history, {len(cards)} project pages"
        + (f", {len(model_entries)} model pages" if model_entries else "")
        + (f", {len(technique_entries)} technique pages" if technique_entries else "")
        + ")"
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
