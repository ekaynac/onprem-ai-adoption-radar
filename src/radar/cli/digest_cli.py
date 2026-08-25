"""``radar digest`` — weekly digest (page + cards + feeds + webhook)."""

from __future__ import annotations

from pathlib import Path

import typer

from radar.cli._shared import console


digest_app = typer.Typer(
    help="Weekly digest (page + cards + feeds + webhook).", no_args_is_help=True
)


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
    from radar.reports.auxiliary_feeds import write_digest_feeds
    from radar.reports.digest import build_digest
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
    write_digest_feeds(
        out_dir,
        digests=all_entries,
        site_title=site_title,
        base_url=base,
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
            return await webhook.send_digest_notification(
                notify_config,
                digest,
                client,
                page_url=page_url if base else None,
            )

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
