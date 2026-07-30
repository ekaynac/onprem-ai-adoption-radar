"""Strict release trust-lifecycle state machine."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from radar.intelligence.contracts import (
    LifecycleState,
    LifecycleTransition,
    Release,
)


ALLOWED_TRANSITIONS = {
    LifecycleState.DETECTED: {LifecycleState.VERIFIED},
    LifecycleState.VERIFIED: {LifecycleState.QUALIFIED},
    LifecycleState.QUALIFIED: {LifecycleState.RECOMMENDED},
    LifecycleState.RECOMMENDED: set(),
}


class InvalidLifecycleTransition(ValueError):
    """A requested lifecycle transition violates trust ordering."""


class LifecycleRepository(Protocol):
    def get_release_required(self, release_id: str) -> Release: ...

    def append_lifecycle_transition(
        self,
        transition: LifecycleTransition,
    ) -> None: ...

    def set_release_lifecycle(
        self,
        release_id: str,
        lifecycle: LifecycleState,
    ) -> None: ...


class LifecycleService:
    def __init__(self, repository: LifecycleRepository):
        self.repository = repository

    def transition(
        self,
        release_id: str,
        target: LifecycleState,
        *,
        reason: str,
        evidence_ids: list[str],
        now: datetime,
    ) -> None:
        release = self.repository.get_release_required(release_id)
        if target not in ALLOWED_TRANSITIONS[release.lifecycle]:
            raise InvalidLifecycleTransition(
                f"{release.lifecycle.value} -> {target.value} is not allowed"
            )
        if not evidence_ids:
            raise InvalidLifecycleTransition(
                "Lifecycle transitions require evidence"
            )
        self.repository.append_lifecycle_transition(
            LifecycleTransition(
                release_id=release_id,
                from_state=release.lifecycle,
                to_state=target,
                observed_at=now,
                reason=reason,
                evidence_ids=sorted(set(evidence_ids)),
            )
        )
        self.repository.set_release_lifecycle(release_id, target)
