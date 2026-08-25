"""``radar alerts`` — stack-profile alert computation + webhook delivery."""

from __future__ import annotations

from pathlib import Path

import typer

from radar.cli._shared import BUNDLED_ROOT, console


alerts_app = typer.Typer(
    help="Stack-profile alerts: compute + webhook delivery.",
    no_args_is_help=True,
)


@alerts_app.command("notify")
def alerts_notify(
    root: Path = typer.Option(Path("."), help="Project root."),
    profile_config: Path | None = typer.Option(
        None,
        "--profile-config",
        help="Stack-profile YAML (defaults to config/stack-profile-demo.yaml).",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        help="Published site URL; adds deep links to the delivered message.",
    ),
) -> None:
    """Push NEW alerts for the configured profile to the notify webhook.

    Exactly-once per alert id (append-only delivery log); skips visibly
    when notify is disabled in config or no webhook URL is present.
    """
    import asyncio
    from datetime import UTC, datetime

    import httpx

    from radar.intelligence.alerts import build_alerts, load_demo_profile
    from radar.notify.alert_delivery import send_alert_notification
    from radar.storage.alert_delivery_log import (
        DeliveredAlert,
        append_delivered_alerts,
        load_delivered_alerts,
    )
    from radar.storage.config import ConfigError, load_config

    config_path = root / "data" / "config.yaml"
    if not config_path.exists():
        console.print("[yellow]No data/config.yaml; alert delivery skipped.[/yellow]")
        return
    try:
        notify_config = load_config(config_path).notify
    except ConfigError as exc:
        console.print(f"[yellow]Alert delivery skipped: {exc}[/yellow]")
        return
    if not notify_config.enabled or not notify_config.webhook_url:
        console.print(
            "[yellow]Alert delivery skipped: notify is disabled or "
            "RADAR_WEBHOOK_URL is unset (enable notify: in config).[/yellow]"
        )
        return

    profile_path = profile_config or root / "config" / "stack-profile-demo.yaml"
    if not profile_path.exists():
        profile_path = BUNDLED_ROOT / "config" / "stack-profile-demo.yaml"
    profile = load_demo_profile(profile_path)
    now = datetime.now(UTC)
    feed = build_alerts(
        root, devices=profile.devices, stack=profile.stack, now=now
    )
    log_path = root / "data" / "alerts-delivered.jsonl"
    delivered = {
        row.alert_id
        for row in load_delivered_alerts(log_path)
        if row.profile == profile.name
    }
    new_alerts = [
        alert for alert in feed["alerts"] if alert["id"] not in delivered
    ]
    if not new_alerts:
        console.print("No new alerts to deliver.")
        return

    async def _run() -> bool:
        async with httpx.AsyncClient(
            timeout=notify_config.timeout_seconds
        ) as client:
            return await send_alert_notification(
                notify_config, new_alerts, profile.name, client, base_url
            )

    sent = asyncio.run(_run())
    if sent:
        append_delivered_alerts(
            log_path,
            [
                DeliveredAlert(
                    alert_id=alert["id"],
                    profile=profile.name,
                    delivered_at=now,
                )
                for alert in new_alerts
            ],
        )
        console.print(
            f"Delivered {len(new_alerts)} new alert(s) for "
            f"“{profile.name}” → {log_path.relative_to(root)}"
        )
    else:
        console.print(
            "[yellow]Webhook delivery failed; alerts stay undelivered "
            "and will retry next cycle.[/yellow]"
        )
