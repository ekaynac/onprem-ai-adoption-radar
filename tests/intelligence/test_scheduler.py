from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from typer.testing import CliRunner

from radar.cli import app
from radar.intelligence.jobs import JobKind
from radar.intelligence.scheduler import build_scheduler, job_idempotency_key


def test_scheduler_has_platform_wide_freshness_cadence() -> None:
    scheduler = build_scheduler(lambda _kind: None)
    jobs = {job.id: job for job in scheduler.get_jobs()}

    assert set(jobs) == {
        "discovery",
        "enrichment",
        "qualification",
        "recommendations",
        "verification",
    }
    assert isinstance(jobs["discovery"].trigger, IntervalTrigger)
    assert jobs["discovery"].trigger.interval == timedelta(hours=2)
    assert isinstance(jobs["enrichment"].trigger, CronTrigger)
    assert str(jobs["enrichment"].trigger.fields[5]) == "3"
    assert str(jobs["enrichment"].trigger.fields[6]) == "0"
    assert isinstance(jobs["qualification"].trigger, CronTrigger)
    assert str(jobs["qualification"].trigger.fields[5]) == "3"
    assert str(jobs["qualification"].trigger.fields[6]) == "15"
    assert isinstance(jobs["recommendations"].trigger, CronTrigger)
    assert str(jobs["recommendations"].trigger.fields[5]) == "3"
    assert str(jobs["recommendations"].trigger.fields[6]) == "30"
    assert isinstance(jobs["verification"].trigger, CronTrigger)
    assert str(jobs["verification"].trigger.fields[4]) == "sun"
    assert str(jobs["verification"].trigger.fields[5]) == "4"


def test_job_idempotency_keys_follow_schedule_windows() -> None:
    at = datetime(2026, 7, 30, 11, 47, tzinfo=UTC)

    assert job_idempotency_key(JobKind.DISCOVERY, at) == "discovery:2026-07-30T10"
    assert job_idempotency_key(JobKind.VERIFY_NEW, at) == "verify-new:2026-07-30T10"
    assert job_idempotency_key(JobKind.ENRICHMENT, at) == "enrichment:2026-07-30"
    assert job_idempotency_key(JobKind.QUALIFICATION, at) == "qualification:2026-07-30"
    assert (
        job_idempotency_key(JobKind.RECOMMENDATIONS, at)
        == "recommendations:2026-07-30"
    )
    assert job_idempotency_key(JobKind.VERIFICATION, at) == "verification:2026-W31"


def test_discovery_cycle_verifies_new_releases_after_ingestion() -> None:
    calls: list[JobKind] = []
    scheduler = build_scheduler(calls.append)

    discovery = {job.id: job for job in scheduler.get_jobs()}["discovery"]
    discovery.func()

    assert calls == [JobKind.DISCOVERY, JobKind.VERIFY_NEW]


def test_run_command_records_an_idempotent_job(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(
        "RADAR_DATABASE_URL",
        f"sqlite:///{tmp_path / 'intelligence.db'}",
    )
    runner = CliRunner()

    first = runner.invoke(
        app,
        ["intelligence-run", "discovery", "--root", str(tmp_path)],
    )
    second = runner.invoke(
        app,
        ["intelligence-run", "discovery", "--root", str(tmp_path)],
    )

    assert first.exit_code == 0
    assert '"status": "completed"' in first.stdout
    assert second.exit_code == 0
    assert '"status": "skipped"' in second.stdout
