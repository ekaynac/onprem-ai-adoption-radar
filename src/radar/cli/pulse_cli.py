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


def _questions_path(root: Path) -> Path:
    path = root / "config" / "pulse-questions.yaml"
    return path if path.exists() else BUNDLED_ROOT / "config" / "pulse-questions.yaml"


@pulse_app.command("triage")
def pulse_triage(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """Label new Pulse items with Jev (TYPESAFE_API_KEY), falling back to rules."""
    import asyncio
    from datetime import UTC, datetime

    import httpx

    from radar.pulse.classify import JevEngine
    from radar.pulse.config import load_pulse_config
    from radar.pulse.jev import jev_api_key
    from radar.pulse.pipeline import ITEMS_PATH
    from radar.pulse.questions import load_questions
    from radar.pulse.store import load_items
    from radar.pulse.triage import (
        LABELS_PATH,
        append_labels,
        load_labels,
        pending,
        prune_labels,
        triage,
    )

    config = load_pulse_config(_pulse_config_path(root))
    questions = load_questions(_questions_path(root))
    items = load_items(root / ITEMS_PATH)
    labels_path = root / LABELS_PATH
    api_key = jev_api_key(root)
    if api_key is None:
        console.print("[yellow]TYPESAFE_API_KEY not set: triaging with rules only "
                      "(labels are marked engine=rules).[/yellow]")
    todo = pending(items, questions, load_labels(labels_path), primary_available=api_key is not None)
    now = datetime.now(UTC)

    async def _run():
        async with httpx.AsyncClient(timeout=60.0) as client:
            engine = JevEngine(client, api_key) if api_key else None
            return await triage(todo, questions, engine, now,
                                config.triage.token_budget_per_run)

    report = asyncio.run(_run())
    append_labels(labels_path, report.labels)
    prune_labels(labels_path, {item.id for item in items})

    cost = report.input_tokens * 42 / 1_000_000_000
    engines = ", ".join(f"{k}={v}" for k, v in sorted(report.engine_counts.items())) or "none"
    console.print(f"Triaged {len(todo)} item(s): {engines}; "
                  f"{report.input_tokens} input tokens (~${cost:.4f})")
    if report.budget_exhausted:
        console.print("[yellow]Token budget reached: remaining items used rules.[/yellow]")
    if report.circuit_open:
        console.print("[red]Jev failed repeatedly: circuit opened, rules used for the rest.[/red]")
    for error in report.errors[:5]:
        console.print(f"  [yellow]{error}[/yellow]")


@pulse_app.command("top")
def pulse_top(
    root: Path = typer.Option(Path("."), help="Project root."),
    lane: str = typer.Option("news", help="model | paper | repo | news"),
    limit: int = typer.Option(10, min=1, max=100),
    show_hidden: bool = typer.Option(False, help="Also list hidden items."),
) -> None:
    """Print a lane's ranking with the reasons behind every position."""
    from radar.pulse.items import Lane
    from radar.pulse.pipeline import ITEMS_PATH
    from radar.pulse.rank import Bucket, rank
    from radar.pulse.store import load_items
    from radar.pulse.triage import LABELS_PATH, load_labels

    try:
        wanted = Lane(lane)
    except ValueError as exc:
        raise typer.BadParameter(f"unknown lane {lane!r}") from exc
    items = [i for i in load_items(root / ITEMS_PATH) if i.lane is wanted]
    ranked = rank(items, load_labels(root / LABELS_PATH))
    shown = [r for r in ranked if show_hidden or r.bucket is not Bucket.HIDDEN][:limit]
    for entry in shown:
        why = "; ".join(entry.reasons)
        console.print(f"{entry.score:5.2f} [{entry.bucket.value:9}] {entry.item.title[:70]}"
                      f"  [dim]({why}; {entry.engine or 'untriaged'})[/dim]")
    hidden = sum(1 for r in ranked if r.bucket is Bucket.HIDDEN)
    console.print(f"[dim]{len(ranked)} {lane} item(s); {hidden} hidden[/dim]")


@pulse_app.command("gold-sample")
def pulse_gold_sample(
    root: Path = typer.Option(Path("."), help="Project root."),
    out: Path = typer.Option(..., help="Markdown checklist to write (must not exist)."),
    seed: int = typer.Option(20260930, help="Sampling seed (reproducible)."),
) -> None:
    """Write a gold-set checklist plus a frozen item snapshot next to it."""
    from radar.pulse.evaluate import DEFAULT_PER_LANE, render_gold, sample_gold
    from radar.pulse.pipeline import ITEMS_PATH
    from radar.pulse.store import load_items, save_items

    if out.exists():
        raise typer.BadParameter(f"{out} exists; refusing to overwrite owner ticks")
    items = sample_gold(load_items(root / ITEMS_PATH), DEFAULT_PER_LANE, seed)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_gold(items, f"Pulse gold set ({out.stem})"), encoding="utf-8")
    save_items(out.with_suffix(".items.jsonl"), items)
    console.print(f"Wrote {len(items)} item(s) to {out} (+ .items.jsonl snapshot)")


@pulse_app.command("eval")
def pulse_eval(
    root: Path = typer.Option(Path("."), help="Project root."),
    gold: Path = typer.Option(..., help="Ticked gold-set checklist."),
) -> None:
    """Score the ranking, Jev vs rules-only, against the owner's gold set.

    Re-triages the frozen snapshot, so the result does not depend on what is
    still inside the Pulse window or in data/.
    """
    import asyncio
    from datetime import UTC, datetime

    import httpx

    from radar.pulse.classify import JevEngine
    from radar.pulse.evaluate import evaluate, parse_gold
    from radar.pulse.jev import jev_api_key
    from radar.pulse.questions import load_questions
    from radar.pulse.rank import rank
    from radar.pulse.store import load_items
    from radar.pulse.triage import needs_triage, triage

    marks = parse_gold(gold.read_text(encoding="utf-8"))
    if not any(marks.values()):
        raise typer.BadParameter(f"{gold} has no ticked items yet")
    items = [i for i in load_items(gold.with_suffix(".items.jsonl")) if i.id in marks]
    to_label = [i for i in items if needs_triage(i)]
    questions = load_questions(_questions_path(root))
    now = datetime.now(UTC)
    api_key = jev_api_key(root)

    async def _labels(use_jev: bool):
        async with httpx.AsyncClient(timeout=60.0) as client:
            engine = JevEngine(client, api_key) if use_jev and api_key else None
            report = await triage(to_label, questions, engine, now, token_budget=10_000_000)
        return {label.item_id: label for label in report.labels}, report

    runs = [("rules", False)] + ([("jev", True)] if api_key else [])
    if not api_key:
        console.print("[yellow]TYPESAFE_API_KEY not set: scoring rules only.[/yellow]")
    for name, use_jev in runs:
        labels, report = asyncio.run(_labels(use_jev))
        extra = f" ({report.input_tokens} tokens, {len(report.errors)} errors)" if use_jev else ""
        console.print(f"[bold]{name}[/bold]{extra}")
        for score in evaluate(rank(items, labels), marks):
            console.print(
                f"  {score.lane:6} labelled={score.labelled:3} wanted={score.wanted:3} "
                f"shown={score.shown:3} precision={score.precision:.2f} "
                f"recall={score.recall:.2f} F1={score.f1:.2f}"
            )
