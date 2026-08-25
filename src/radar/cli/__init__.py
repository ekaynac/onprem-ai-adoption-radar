"""Command line interface for the adoption radar.

This package is a split of the former monolithic ``radar/cli.py`` into
per-domain command modules. The CLI surface is unchanged: every command
name, option, and help text is identical.

Wiring strategy: typer lists top-level commands in decorator-registration
order and groups in ``add_typer`` order, and the original file interleaved
domains (e.g. the intelligence commands sit between ``init`` and ``scan``),
so this module owns ALL wiring order:

- Domain group modules (``seed_cli``, ``models_cli``, …) define their own
  sub-Typer at module level and decorate their commands on it; they are
  added here with ``app.add_typer(...)`` in the original order.
- Top-level flat commands are plain functions in their domain modules,
  registered here via ``app.command(...)`` / ``app.callback()`` in exactly
  the original cli.py order. No new sub-command groups were introduced —
  all flat commands stay flat.

Monkeypatch seams: tests patch internals via module attributes. The only
such seam is ``_verify_fetch_hf_model``, defined in
``radar.cli.models_cli`` — the module whose ``models verify`` command
resolves it as a module global. Tests that previously patched
``radar.cli._verify_fetch_hf_model`` must patch
``radar.cli.models_cli._verify_fetch_hf_model`` instead; the seam is
deliberately NOT re-exported here so a stale patch target cannot silently
stop affecting the executed code path.
"""

from __future__ import annotations

import typer

from radar.cli import (
    alerts_cli,
    capacity_cli,
    desk_cli,
    digest_cli,
    history_cli,
    intelligence_cli,
    models_cli,
    news_cli,
    project_cli,
    reports_cli,
    research_cli,
    seed_cli,
    trending_cli,
)


app = typer.Typer(
    help="Agent/tooling adoption radar for on-prem AI workflows.",
    no_args_is_help=True,
)

# Root callback (was @app.callback() def root in cli.py).
app.callback()(project_cli.root)

# Flat top-level commands, in the original cli.py registration order
# (typer's --help lists commands in this order).
app.command()(project_cli.version)
app.command()(project_cli.backtest)
app.command()(project_cli.init)
app.command("intelligence-migrate")(intelligence_cli.intelligence_migrate)
app.command("intelligence-lineage-backfill")(intelligence_cli.intelligence_lineage_backfill)
app.command("intelligence-lineage-triage")(intelligence_cli.intelligence_lineage_triage)
app.command("intelligence-shadow")(intelligence_cli.intelligence_shadow)
app.command("intelligence-replay-events")(intelligence_cli.intelligence_replay_events)
app.command("intelligence-state-pack")(intelligence_cli.intelligence_state_pack)
app.command("intelligence-state-restore")(intelligence_cli.intelligence_state_restore)
app.command("intelligence-run")(intelligence_cli.intelligence_run)
app.command("intelligence-scheduler")(intelligence_cli.intelligence_scheduler)
app.command()(project_cli.scan)
app.command()(reports_cli.report)
app.command()(project_cli.discover)
app.command()(project_cli.override)
app.command()(project_cli.trial)
app.command("calibrate-report")(reports_cli.calibrate_report)
app.command("scan-health")(reports_cli.scan_health_cmd)
app.command()(reports_cli.movers)
app.command()(project_cli.sandbox)
app.command()(reports_cli.export)
app.command()(project_cli.compare)
app.command()(project_cli.mcp)
app.command()(project_cli.serve)

# Command groups, in the original add_typer order (typer's --help lists
# groups after flat commands, in this order).
app.add_typer(seed_cli.seed_app, name="seed")
app.add_typer(models_cli.models_app, name="models")
app.add_typer(research_cli.research_app, name="research")
app.add_typer(trending_cli.trending_app, name="trending")
app.add_typer(digest_cli.digest_app, name="digest")
app.add_typer(desk_cli.desk_app, name="desk")
app.add_typer(news_cli.news_app, name="news")
app.add_typer(alerts_cli.alerts_app, name="alerts")
app.add_typer(capacity_cli.capacity_app, name="capacity")
app.add_typer(history_cli.history_app, name="history")


def main() -> None:
    """Entrypoint for the installed console script."""
    app()
