"""Source health counters and circuit-breaker policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol


@dataclass(frozen=True)
class SourceHealthState:
    source_id: str
    consecutive_failures: int
    last_error: str | None = None
    last_failure_at: datetime | None = None
    last_success_at: datetime | None = None
    latency_ms: float | None = None
    items_count: int | None = None
    circuit_open_until: datetime | None = None


class SourceHealthRepository(Protocol):
    def increment_source_failure(
        self,
        source_id: str,
        error: str,
        now: datetime,
    ) -> SourceHealthState: ...

    def open_source_circuit(
        self,
        source_id: str,
        until: datetime,
    ) -> None: ...

    def record_source_success(
        self,
        source_id: str,
        latency_ms: float,
        items: int,
        now: datetime,
    ) -> SourceHealthState: ...

    def get_source_health(
        self,
        source_id: str,
    ) -> SourceHealthState | None: ...


class SourceHealthService:
    def __init__(self, repository: SourceHealthRepository):
        self.repository = repository

    def record_failure(
        self,
        source_id: str,
        error: str,
        now: datetime,
    ) -> SourceHealthState:
        state = self.repository.increment_source_failure(
            source_id,
            error,
            now,
        )
        if state.consecutive_failures >= 5:
            self.repository.open_source_circuit(
                source_id,
                until=now + timedelta(hours=2),
            )
            refreshed = self.repository.get_source_health(source_id)
            assert refreshed is not None
            return refreshed
        return state

    def record_success(
        self,
        source_id: str,
        *,
        latency_ms: float,
        items: int,
        now: datetime,
    ) -> SourceHealthState:
        return self.repository.record_source_success(
            source_id,
            latency_ms,
            items,
            now,
        )

    def should_skip(self, source_id: str, now: datetime) -> bool:
        state = self.repository.get_source_health(source_id)
        return bool(
            state
            and state.circuit_open_until
            and now < state.circuit_open_until
        )
