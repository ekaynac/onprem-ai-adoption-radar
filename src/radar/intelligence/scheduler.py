"""Built-in cadence for the platform-wide freshness policy."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from apscheduler.schedulers.background import (  # type: ignore[import-untyped]
    BackgroundScheduler,
)

from radar.intelligence.jobs import JobKind


def job_idempotency_key(kind: JobKind, at: datetime) -> str:
    if kind is JobKind.DISCOVERY:
        slot_hour = at.hour - (at.hour % 2)
        return f"{kind.value}:{at:%Y-%m-%d}T{slot_hour:02d}"
    if kind is JobKind.VERIFICATION:
        iso_year, iso_week, _weekday = at.isocalendar()
        return f"{kind.value}:{iso_year}-W{iso_week:02d}"
    return f"{kind.value}:{at:%Y-%m-%d}"


def build_scheduler(
    run_job: Callable[[JobKind], None],
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        run_job,
        "interval",
        hours=2,
        args=[JobKind.DISCOVERY],
        id="discovery",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_job,
        "cron",
        hour=3,
        minute=0,
        args=[JobKind.ENRICHMENT],
        id="enrichment",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_job,
        "cron",
        day_of_week="sun",
        hour=4,
        minute=0,
        args=[JobKind.VERIFICATION],
        id="verification",
        max_instances=1,
        coalesce=True,
    )
    return scheduler
