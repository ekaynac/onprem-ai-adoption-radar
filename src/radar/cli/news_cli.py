"""``radar news`` — feed sweep + LLM change classification."""

from __future__ import annotations

from pathlib import Path

import typer

from radar.cli._shared import BUNDLED_ROOT, console


news_app = typer.Typer(
    help="Newsroom: feed sweep + LLM change classification.",
    no_args_is_help=True,
)


def _news_config_path(root: Path) -> Path:
    path = root / "config" / "news-sources.yaml"
    if path.exists():
        return path
    return BUNDLED_ROOT / "config" / "news-sources.yaml"


@news_app.command("scan")
def news_scan(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """Sweep configured feeds and append new (deduped) news items."""
    import asyncio
    from datetime import UTC, datetime

    import httpx

    from radar.constants import RSS_ACCEPT, RSS_USER_AGENT
    from radar.discovery.news_sweep import load_news_sources, sweep_news
    from radar.storage.news_log import append_news_items

    config = load_news_sources(_news_config_path(root))
    now = datetime.now(UTC)

    async def _run():
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": RSS_USER_AGENT, "Accept": RSS_ACCEPT},
        ) as client:
            return await sweep_news(config, client, now)

    result = asyncio.run(_run())
    out_path = root / "data" / "news-observations.jsonl"
    appended = append_news_items(out_path, result.items)
    from radar.storage.source_health_log import (
        SourceHealthRecord,
        SourceOutcome,
        append_source_health,
    )

    append_source_health(
        root / "data" / "source-health.jsonl",
        SourceHealthRecord(
            run_id=f"news-{now.isoformat()}",
            observed_at=now,
            sources={
                f"news:{source_id}": SourceOutcome(
                    count=outcome["count"],
                    status=outcome["status"],
                )
                for source_id, outcome in result.outcomes.items()
            },
        ),
    )
    console.print(
        f"Observed {len(result.items)} news item(s), {appended} new "
        f"→ {out_path.relative_to(root)}"
    )
    for source_id, outcome in sorted(result.outcomes.items()):
        console.print(
            f"  {source_id}: {outcome['count']} item(s), {outcome['status']}"
        )


@news_app.command("classify")
def news_classify(
    root: Path = typer.Option(Path("."), help="Project root."),
    engine: str = typer.Option(
        "auto",
        help="auto | api | claude-cli. auto prefers the API key, then the "
        "local claude CLI (subscription auth), then skips visibly.",
    ),
    limit: int = typer.Option(
        0, help="Override the per-run item budget (0 = use config)."
    ),
) -> None:
    """Classify unclassified items via Claude (budget-bounded).

    Skips visibly — exit code 0 — when classification is disabled or no
    engine is available; the newsroom then stays a raw firehose.
    """
    from datetime import UTC, datetime

    from radar.discovery.news_classify import (
        build_anthropic_client,
        classify_news,
    )
    from radar.discovery.news_claude_cli import build_claude_cli_client
    from radar.discovery.news_sweep import load_news_sources
    from radar.storage.news_log import (
        append_news_classifications,
        load_news_classifications,
        load_news_items,
    )

    config = load_news_sources(_news_config_path(root))
    if not config.classification.enabled:
        console.print("[yellow]News classification disabled in config; skipping.[/yellow]")
        return
    if engine not in {"auto", "api", "claude-cli"}:
        console.print(f"[red]Unknown engine '{engine}'.[/red]")
        raise typer.Exit(code=2)
    client = None
    engine_used = engine
    if engine in {"auto", "api"}:
        client = build_anthropic_client()
        engine_used = "api"
    if client is None and engine in {"auto", "claude-cli"}:
        client = build_claude_cli_client()
        engine_used = "claude-cli"
    if client is None:
        console.print(
            "[yellow]No classification engine available (no ANTHROPIC_API_KEY "
            "and no claude CLI on PATH); skipping — newsroom stays raw-only "
            "this run.[/yellow]"
        )
        return
    console.print(f"Engine: {engine_used}")

    items = load_news_items(root / "data" / "news-observations.jsonl")
    classified_path = root / "data" / "news-classified.jsonl"
    done = {row.news_id for row in load_news_classifications(classified_path)}
    pending = sorted(
        (item for item in items if item.id not in done),
        key=lambda item: (item.published_at or item.observed_at),
        reverse=True,
    )
    if not pending:
        console.print("No unclassified news items.")
        return
    now = datetime.now(UTC)
    classification_config = config.classification
    if limit > 0:
        classification_config = classification_config.model_copy(
            update={"max_items_per_run": limit}
        )
    result = classify_news(pending, classification_config, client, now, root=root)
    appended = append_news_classifications(classified_path, result.classifications)

    # Close the learning loop: the analyst's component slugs become
    # tomorrow's gate vocabulary (nothing stays hardcoded).
    from radar.knowledge import learn_from_classifications

    learned_count = learn_from_classifications(root, result.classifications, now=now)

    console.print(
        f"Classified {appended} item(s) with {config.classification.model} "
        f"→ {classified_path.relative_to(root)}; "
        f"{len(result.failures)} failure(s), {result.over_budget} deferred to "
        f"future runs by budget; vocabulary +{learned_count}"
    )
    for news_id, reason in result.failures:
        console.print(f"  [yellow]{news_id}: {reason}[/yellow]")
