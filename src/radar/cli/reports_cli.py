"""Reporting/ops commands: report, calibrate-report, scan-health, movers, export.

Plain functions: the shared ``app`` in ``radar.cli`` registers them (in the
original cli.py order) via ``app.command(...)``.
"""

from __future__ import annotations

import logging
import shutil
from datetime import UTC
from pathlib import Path
from typing import Any

import typer

from radar.cli._shared import console
from radar.orchestrator import RadarOrchestrator
from radar.reports.markdown import render_markdown_report
from radar.scoring.profiles import UnknownProfileError


logger = logging.getLogger(__name__)

EXPORT_RESEARCH_STALE_DAYS = 2


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

    report_md = build_calibration_report(scored, ring_by_project, history_events=events)
    console.print(render_calibration_markdown(report_md))
    # Quality gate: fail only on collapse (one ring, or >80% in a single ring),
    # which means scoring stopped discriminating — a real regression.
    if check and not report_md.discriminates:
        console.print(
            "[red]Quality gate failed:[/red] rings do not discriminate."
        )
        raise typer.Exit(code=1)


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
    except Exception as exc:
        logger.warning("Could not read latest research run metadata: %s", exc)
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
    """Render the public React command center and compatibility artifacts."""
    from datetime import datetime

    # Validate at the boundary: a non-empty base URL must be absolute http(s),
    # otherwise the feed self/link URLs would be silently malformed.
    if base_url and not base_url.startswith(("http://", "https://")):
        raise typer.BadParameter(
            "--base-url must be an absolute http(s) URL, e.g. https://user.github.io/repo",
            param_hint="--base-url",
        )

    from radar.models import DecisionCard
    from radar.models_radar.entities import ModelEntry
    from radar.models_radar.history import ModelHistoryEvent, load_model_events
    from radar.storage.config import ConfigError, load_config
    from radar.storage.digest_log import load_digests
    from radar.storage.history_store import HistoryStore
    from radar.storage.metrics_store import MetricsStore
    from radar.storage.model_metrics_store import ModelMetricsStore
    from radar.storage.source_health_store import SourceHealthStore
    from radar.web.public_context import (
        load_public_model_profiles,
        load_public_project_bundle,
        load_public_research_entries,
    )
    from radar.web.scan_health import latest_tool_scan_meta
    from radar.web.source_health import summarize_source_health
    from radar.web.static_site import render_static_site

    orchestrator = RadarOrchestrator(root)
    cards = orchestrator.latest_cards()
    project_baseline_note = None
    if not cards:
        project_bundle = load_public_project_bundle(root)
        cards = [
            DecisionCard.model_validate(row)
            for row in project_bundle.projects
        ]
        if project_bundle.mode == "last_published_baseline":
            baseline_time = (
                project_bundle.generated_at.astimezone(UTC).strftime(
                    "%Y-%m-%d %H:%M UTC"
                )
                if project_bundle.generated_at is not None
                else "an unknown date"
            )
            project_baseline_note = (
                f"Project decisions use the last published baseline from {baseline_time}; "
                "a current scan projection was unavailable at export."
            )

    history = HistoryStore(root / "data" / "radar.db")
    history.initialize()
    orchestrator.reconcile_history()
    # all_summaries(), not summaries(): a project entirely corrected away
    # must still show its raw timeline and feed entries here.
    timelines = [
        {"summary": s, "events": history.history_for(s.project)}
        for s in sorted(history.all_summaries(), key=lambda s: s.last_change_at, reverse=True)
    ]

    # Tenure credential (Task 1, differentiation pass): "On radar N days ·
    # RING since <date> · N ring changes", computed over the effective
    # (outage-corrected) timeline. None entries (fully-corrected projects)
    # are dropped rather than threaded through as null tenure lines.
    from radar.web.tenure import model_tenure, project_tenure

    tenure_by_project = {
        c.project: line
        for c in cards
        if (line := project_tenure(history.history_for(c.project), datetime.now(UTC)))
    }

    metrics = MetricsStore(root / "data" / "radar.db")
    metrics.initialize()
    metrics_by_project = {c.project: metrics.history_for(c.project) for c in cards}

    # HN chip (Task 6, differentiation pass): only projects with a positive
    # latest hn_mentions get a chip on the static index page.
    hn_by_project = {
        p: rows[-1].hn_mentions
        for p, rows in metrics_by_project.items()
        if rows and rows[-1].hn_mentions
    }

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
    model_entries = [
        ModelEntry.model_validate(card)
        for card in load_public_model_profiles(root).values()
    ]
    model_events = load_model_events(root / "data" / "model-history.jsonl")

    # Model download history (Task 3, differentiation pass): drives the
    # sparkline on each model detail page.
    model_metrics_store = ModelMetricsStore(root / "data" / "radar.db")
    model_metrics_store.initialize()
    model_metrics_by_id = {e.id: model_metrics_store.history_for(e.id) for e in model_entries}

    # Tenure credential for model detail pages: group the model-history log
    # by model_id, then compute one tenure line per model (no corrections
    # concept for models — see radar.web.tenure.model_tenure).
    model_events_by_id: dict[str, list[ModelHistoryEvent]] = {}
    for event in model_events:
        model_events_by_id.setdefault(event.model_id, []).append(event)
    model_tenure_by_id = {
        model_id: line
        for model_id, events in model_events_by_id.items()
        if (line := model_tenure(events, datetime.now(UTC)))
    }

    # Copy model-history.jsonl into the site so it's available as a download.
    model_history_src = root / "data" / "model-history.jsonl"
    out.mkdir(parents=True, exist_ok=True)
    if model_history_src.exists():
        shutil.copy2(model_history_src, out / "model-history.jsonl")

    # Technique entries + events (optional: only present after a `radar research scan`).
    from radar.research_radar.entities import ImplKind
    from radar.research_radar.history import load_technique_events as _load_tech_events

    technique_entries = load_public_research_entries(root)
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

    # Platform capability matrix (Task 7): a bundled, cited seed — not scan
    # output — so root/config overrides the packaged copy same as the model/
    # technique seeds (shared resolution: load_platform_entries); a load
    # failure degrades to no platforms.html rather than failing the export.
    from radar.mcp_server.model_queries import load_platform_entries
    from radar.models_radar.platform_matrix import PlatformMatrixError

    try:
        platform_entries = load_platform_entries(root)
    except PlatformMatrixError as exc:
        console.print(f"[yellow]⚠ platform matrix unreadable ({exc}); skipping platforms.html[/yellow]")
        platform_entries = []

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
        except Exception as exc:
            logger.warning("Config unreadable for technique export: %s", exc)
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

    frontend_source = root / "frontend" / "package.json"
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
        tenure_by_project=tenure_by_project or None,
        model_tenure_by_id=model_tenure_by_id or None,
        model_metrics_by_id=model_metrics_by_id or None,
        hn_by_project=hn_by_project or None,
        platform_entries=platform_entries or None,
        project_baseline_note=project_baseline_note,
        write_public_feeds=not frontend_source.exists(),
    )
    if frontend_source.exists():
        from radar.web.react_export import (
            build_react_frontend,
            export_react_site,
        )

        frontend_build = build_react_frontend(root, static=True)
        export_react_site(
            root,
            out,
            frontend_dir=frontend_build,
            base_url=base_url,
            generated_at=generated_at,
        )
        index = out / "index.html"
    console.print(
        f"Wrote {index.parent}/ (index, compare, history, {len(cards)} project pages"
        + (f", {len(model_entries)} model pages" if model_entries else "")
        + (f", {len(technique_entries)} technique pages" if technique_entries else "")
        + (f", {len(platform_entries)} platforms" if platform_entries else "")
        + ")"
    )
