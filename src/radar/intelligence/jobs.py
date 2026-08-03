"""Durable, idempotent background-job orchestration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol


class JobKind(StrEnum):
    DISCOVERY = "discovery"
    ENRICHMENT = "enrichment"
    VERIFY_NEW = "verify-new"
    VERIFICATION = "verification"
    QUALIFICATION = "qualification"
    RECOMMENDATIONS = "recommendations"
    EXPORT = "export"


class JobStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class JobLease:
    id: str
    kind: JobKind
    idempotency_key: str
    status: JobStatus
    attempt: int
    leased_until: datetime | None
    created_at: datetime
    started_at: datetime
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass(frozen=True)
class JobResult:
    job_id: str
    processed: int = 0
    remaining: int = 0
    processed_ids: tuple[str, ...] = ()
    discovered: int = 0
    created: int = 0
    updated: int = 0
    rejected: int = 0
    conflicted: int = 0
    warnings: tuple[str, ...] = ()


class JobRepository(Protocol):
    def acquire_job(
        self,
        *,
        kind: str,
        idempotency_key: str,
        leased_until: datetime,
        now: datetime,
    ) -> JobLease | None: ...

    def complete_job(
        self,
        job_id: str,
        result: dict[str, Any],
        now: datetime,
    ) -> None: ...

    def fail_job(self, job_id: str, error: str, now: datetime) -> None: ...

    def get_job(self, job_id: str) -> JobLease | None: ...

    def latest_processed_attempts(self, kind: str) -> dict[str, datetime]: ...


class JobService:
    def __init__(self, repository: JobRepository, lease_seconds: int = 900):
        self.repository = repository
        self.lease_seconds = lease_seconds

    def acquire(
        self,
        kind: JobKind,
        idempotency_key: str,
        now: datetime,
    ) -> JobLease | None:
        return self.repository.acquire_job(
            kind=kind.value,
            idempotency_key=idempotency_key,
            leased_until=now + timedelta(seconds=self.lease_seconds),
            now=now,
        )

    def complete(self, job_id: str, result: JobResult, now: datetime) -> None:
        self.repository.complete_job(job_id, asdict(result), now)

    def fail(self, job_id: str, error: str, now: datetime) -> None:
        self.repository.fail_job(job_id, error, now)

    def get(self, job_id: str) -> JobLease | None:
        return self.repository.get_job(job_id)
