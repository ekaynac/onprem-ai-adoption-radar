from __future__ import annotations

from datetime import UTC, datetime, timedelta

from radar.intelligence.database import Database
from radar.intelligence.jobs import JobKind, JobResult, JobService, JobStatus
from radar.intelligence.repositories import SqlAlchemyIntelligenceRepository


NOW = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)


def make_service(tmp_path, lease_seconds: int = 300) -> JobService:
    database = Database(f"sqlite:///{tmp_path / 'intelligence.db'}")
    database.create_schema()
    repository = SqlAlchemyIntelligenceRepository(database)
    return JobService(repository, lease_seconds=lease_seconds)


def test_only_one_worker_acquires_same_job(tmp_path) -> None:
    service = make_service(tmp_path)

    first = service.acquire(JobKind.DISCOVERY, "discovery:2026-07-30T10", NOW)
    second = service.acquire(JobKind.DISCOVERY, "discovery:2026-07-30T10", NOW)

    assert first is not None
    assert first.attempt == 1
    assert second is None


def test_expired_lease_can_be_reacquired(tmp_path) -> None:
    service = make_service(tmp_path, lease_seconds=60)
    first = service.acquire(JobKind.DISCOVERY, "slot", NOW)
    assert first is not None

    reacquired = service.acquire(
        JobKind.DISCOVERY,
        "slot",
        NOW + timedelta(seconds=61),
    )

    assert reacquired is not None
    assert reacquired.id == first.id
    assert reacquired.attempt == 2


def test_completed_job_is_idempotent(tmp_path) -> None:
    service = make_service(tmp_path)
    lease = service.acquire(JobKind.ENRICHMENT, "daily:2026-07-30", NOW)
    assert lease is not None
    result = JobResult(job_id=lease.id, discovered=12, created=3)

    service.complete(lease.id, result, NOW + timedelta(seconds=5))

    stored = service.get(lease.id)
    assert stored is not None
    assert stored.status is JobStatus.COMPLETED
    assert stored.result == {
        "job_id": lease.id,
        "discovered": 12,
        "created": 3,
        "updated": 0,
        "rejected": 0,
        "conflicted": 0,
        "warnings": [],
    }
    assert (
        service.acquire(
            JobKind.ENRICHMENT,
            "daily:2026-07-30",
            NOW + timedelta(days=1),
        )
        is None
    )


def test_failed_job_can_be_retried(tmp_path) -> None:
    service = make_service(tmp_path)
    lease = service.acquire(JobKind.VERIFICATION, "weekly:2026-W31", NOW)
    assert lease is not None
    service.fail(lease.id, "source timeout", NOW + timedelta(seconds=5))

    failed = service.get(lease.id)
    assert failed is not None
    assert failed.status is JobStatus.FAILED
    assert failed.error == "source timeout"

    retried = service.acquire(
        JobKind.VERIFICATION,
        "weekly:2026-W31",
        NOW + timedelta(seconds=6),
    )
    assert retried is not None
    assert retried.attempt == 2

