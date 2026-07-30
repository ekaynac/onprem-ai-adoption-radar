from __future__ import annotations

from datetime import timedelta

import pytest

from radar.intelligence.contracts import LifecycleState
from radar.intelligence.lifecycle import (
    InvalidLifecycleTransition,
    LifecycleService,
)

from .lifecycle_helpers import NOW, RELEASE_ID, lifecycle_repository


def test_cannot_skip_verified_and_qualified(tmp_path) -> None:
    service = LifecycleService(lifecycle_repository(tmp_path))

    with pytest.raises(
        InvalidLifecycleTransition,
        match="detected -> recommended",
    ):
        service.transition(
            RELEASE_ID,
            LifecycleState.RECOMMENDED,
            reason="skip",
            evidence_ids=["evidence:one"],
            now=NOW,
        )


def test_transition_is_recorded_before_projection_changes(tmp_path) -> None:
    repository = lifecycle_repository(tmp_path)
    service = LifecycleService(repository)

    service.transition(
        RELEASE_ID,
        LifecycleState.VERIFIED,
        reason="official evidence complete",
        evidence_ids=["evidence:one"],
        now=NOW + timedelta(minutes=1),
    )

    assert repository.get_release(RELEASE_ID).lifecycle is LifecycleState.VERIFIED
    transitions = repository.list_lifecycle_transitions(RELEASE_ID)
    assert len(transitions) == 1
    assert transitions[0].from_state is LifecycleState.DETECTED
    assert transitions[0].to_state is LifecycleState.VERIFIED
