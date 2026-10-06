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


@pulse_app.command("telegram")
def pulse_telegram(
    root: Path = typer.Option(Path("."), help="Project root."),
    site_url: str = typer.Option("", help="Public site URL for the footer link."),
    dry_run: bool = typer.Option(False, help="Print the message; send and record nothing."),
    force: bool = typer.Option(False, help="Send even if today's digest already went out."),
    not_before_hour: int = typer.Option(
        8, min=0, max=23, help="Earliest local (Europe/Istanbul) hour to send the daily digest.",
    ),
    skip_without_credentials: bool = typer.Option(
        False, help="Exit 0 with a visible notice when the bot secrets are absent (CI).",
    ),
    view_url: str = typer.Option(
        "", help="Read the published pulse.v1.json from this URL instead of local data "
                 "(homelab worker: data over HTTPS, code never auto-updated).",
    ),
    summaries: str = typer.Option(
        "none", help="'claude-cli' adds a one-sentence Turkish explanation per shown item "
                     "via the owner's Claude subscription; 'none' skips it.",
    ),
) -> None:
    """Send today's Pulse digest via the radar bot (TELEGRAM_BOT_TOKEN/CHAT_ID)."""
    import asyncio
    from datetime import UTC, datetime

    import httpx

    from radar.pulse.telegram import (
        LOCAL_TZ,
        STATE_PATH,
        TelegramError,
        load_state,
        local_today,
        mark_sent,
        record_delivery,
        render_digest,
        save_state,
        select_new,
        send_message,
        state_file,
        telegram_credentials,
    )
    from radar.pulse.view import build_pulse_view

    now = datetime.now(UTC)
    today = local_today(now)
    if not dry_run and not force and now.astimezone(LOCAL_TZ).hour < not_before_hour:
        console.print(f"Before {not_before_hour:02d}:00 Istanbul time; the digest waits.")
        return
    if not dry_run and telegram_credentials(root) is None and skip_without_credentials:
        console.print("[yellow]Telegram digest skipped: TELEGRAM_BOT_TOKEN / "
                      "TELEGRAM_CHAT_ID are not configured.[/yellow]")
        return
    state_path = state_file(root, STATE_PATH)
    state = load_state(state_path)
    if state.get("last_sent_date") == today.isoformat() and not force and not dry_run:
        console.print(f"Telegram digest already sent for {today}; skipping.")
        return
    view = _remote_view(view_url) if view_url else build_pulse_view(root, now)
    picks = select_new(view, set(state["delivered"]))
    explanations = _explanations(root, picks, summaries, now) if summaries != "none" else {}
    messages = render_digest(picks, view, site_url, today, explanations=explanations)
    if not messages:
        console.print("Nothing new to send.")
        return
    if dry_run:
        for message in messages:
            console.print(message.text, markup=False, highlight=False)
            console.print("-" * 40)
        return
    credentials = telegram_credentials(root)
    if credentials is None:
        console.print("[yellow]TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set: "
                      "digest not sent.[/yellow]")
        raise typer.Exit(code=1)

    async def _send_one(text: str) -> None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            await send_message(client, *credentials, text)

    sent = 0
    for message in messages:
        try:
            asyncio.run(_send_one(message.text))
        except TelegramError as exc:
            console.print(f"[red]{exc}[/red] ({sent}/{len(messages)} message(s) sent; "
                          "the rest retry next run)")
            raise typer.Exit(code=1) from None
        # Record per message so a mid-digest failure never re-sends earlier parts.
        state = record_delivery(state, list(message.item_ids))
        save_state(state_path, state)
        sent += 1
    save_state(state_path, mark_sent(state, today))
    items = sum(len(m.item_ids) for m in messages)
    console.print(f"Sent Telegram digest: {items} item(s) in {sent} message(s).")


@pulse_app.command("watchdog")
def pulse_watchdog(
    root: Path = typer.Option(Path("."), help="Project root."),
    dry_run: bool = typer.Option(False, help="Print findings; send and record nothing."),
) -> None:
    """Dead-man checks (live site, publish runs, lanes, digest); alerts via Çakır once."""
    import asyncio
    from datetime import UTC, datetime

    import httpx

    from radar.pulse import watchdog as wd
    from radar.pulse.config import load_pulse_config
    from radar.pulse.telegram import STATE_PATH as DIGEST_STATE_PATH
    from radar.pulse.telegram import TelegramError, load_state, state_file, telegram_credentials

    config = load_pulse_config(_pulse_config_path(root))
    if config.watchdog is None:
        raise typer.BadParameter("config/pulse.yaml has no watchdog section")
    watch = config.watchdog
    now = datetime.now(UTC)

    async def _fetch():
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            view, view_error = None, None
            try:
                response = await client.get(watch.site_url.rstrip("/") + "/data/pulse.v1.json")
                response.raise_for_status()
                view = response.json()
            except Exception as exc:
                view_error = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
            runs, runs_error = None, None
            try:
                response = await client.get(
                    f"https://api.github.com/repos/{watch.repo}/actions/workflows/"
                    f"{watch.publish_workflow}/runs",
                    params={"per_page": 20},  # no branch filter: it broke ordering
                    headers={"Accept": "application/vnd.github+json"},
                )
                response.raise_for_status()
                runs = response.json().get("workflow_runs", [])
            except Exception as exc:
                runs_error = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
            return view, view_error, runs, runs_error

    view, view_error, runs, runs_error = asyncio.run(_fetch())
    digest_state = load_state(state_file(root, DIGEST_STATE_PATH))
    findings = [
        *wd.check_site(view, now, view_error),
        *wd.check_publish(runs, runs_error, now),
        *wd.check_digest(digest_state.get("last_sent_date"), now),
    ]
    state_path = state_file(root, wd.STATE_PATH)
    previous = wd.load_state(state_path)
    raised, cleared, active = wd.diff_alerts(previous, findings)
    for finding in findings:
        console.print(f"[yellow]{finding.key}: {finding.message}[/yellow]")
    if not findings:
        console.print("[green]All radar checks healthy.[/green]")
    message = wd.render_alert(raised, cleared, previous)
    if dry_run or message is None:
        if message and dry_run:
            console.print(message, markup=False, highlight=False)
        return

    import os

    # Alerts speak through Çakır; the digest bot (Memati) is the fallback so a
    # missing sentinel token never silences an alarm.
    credentials = telegram_credentials(root)
    alert_token = os.environ.get("TELEGRAM_ALERT_BOT_TOKEN", "").strip()
    if credentials is None:
        console.print("[red]No Telegram credentials: alert not delivered.[/red]")
        raise typer.Exit(code=1)
    token, chat_id = credentials
    try:
        asyncio.run(_send_alert(alert_token or token, chat_id, message))
    except TelegramError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None
    wd.save_state(state_path, active, now)
    console.print(f"Alert sent: {len(raised)} raised, {len(cleared)} resolved.")


async def _send_alert(token: str, chat_id: str, text: str) -> None:
    import httpx

    from radar.pulse.telegram import send_message

    async with httpx.AsyncClient(timeout=30.0) as client:
        await send_message(client, token, chat_id, text)


def _remote_view(url: str) -> dict:
    import httpx

    from radar.pulse.view import validate_view

    try:
        response = httpx.get(url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        return validate_view(response.json())
    except (httpx.HTTPError, ValueError) as exc:
        console.print(f"[red]Published Pulse view unusable ({url}): "
                      f"{type(exc).__name__}: {str(exc).splitlines()[0]}[/red]")
        raise typer.Exit(code=1) from None


def _explanations(root: Path, picks: dict, engine: str, now) -> dict[str, str]:
    """Best effort: a summaries failure never blocks or delays the digest."""
    from radar.pulse.summaries import (
        CACHE_PATH,
        claude_cli_runner,
        load_cache,
        save_cache,
        summarize,
    )
    from radar.pulse.telegram import shown_rows, state_file

    if engine != "claude-cli":
        raise typer.BadParameter(f"unknown summaries engine {engine!r}")
    rows = shown_rows(picks)
    cache_path = state_file(root, CACHE_PATH)
    try:
        cache = load_cache(cache_path)
        cache, added = summarize(rows, cache, claude_cli_runner(), now)
        save_cache(cache_path, cache)
        console.print(f"Summaries: {added} new, {len(rows)} shown item(s).")
    except Exception as exc:
        console.print(f"[yellow]Summaries skipped ({type(exc).__name__}: "
                      f"{str(exc).splitlines()[0][:200] if str(exc) else ''}); "
                      "the digest goes out without them.[/yellow]")
        return {}
    return {row["id"]: cache[row["id"]]["text"] for row in rows if row["id"] in cache}
