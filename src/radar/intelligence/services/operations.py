"""Operational health projection for the unified command center."""

from __future__ import annotations

from typing import Protocol

from pydantic import Field

from radar.intelligence.contracts import FrozenModel, ReviewException
from radar.intelligence.source_health import SourceHealthState


class OperationsSnapshot(FrozenModel):
    source_health: list[SourceHealthState] = Field(default_factory=list)
    open_review_count: int
    stale_claim_count: int


class OperationsRepository(Protocol):
    def list_source_health(self) -> list[SourceHealthState]: ...

    def list_review_exceptions(
        self,
        *,
        open_only: bool = False,
    ) -> list[ReviewException]: ...

    def count_stale_claims(self) -> int: ...


class OperationsService:
    def __init__(self, repository: OperationsRepository):
        self.repository = repository

    def snapshot(self) -> OperationsSnapshot:
        return OperationsSnapshot(
            source_health=self.repository.list_source_health(),
            open_review_count=len(
                self.repository.list_review_exceptions(open_only=True)
            ),
            stale_claim_count=self.repository.count_stale_claims(),
        )
