"""Trending entities: lane, observation row, derived entry."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from radar.discovery.trending_entities import Lane, TrendingEntry, TrendingObservation


def test_observation_round_trips_and_is_frozen():
    obs = TrendingObservation(
        repo="acme/rocket", lane=Lane.ONPREM, stars=1200,
        observed_at=datetime(2026, 7, 5, 7, 0, tzinfo=UTC),
        repo_created_at=datetime(2026, 6, 20, tzinfo=UTC),
        description="fast serving", topics=["llm", "inference"], license="Apache-2.0",
    )

    dumped = obs.model_dump_json()
    assert TrendingObservation.model_validate_json(dumped) == obs
    with pytest.raises(ValidationError):
        obs.stars = 5  # type: ignore[misc]


def test_observation_rejects_unknown_fields_and_defaults():
    obs = TrendingObservation(
        repo="a/b", lane=Lane.BROADER, stars=50,
        observed_at=datetime(2026, 7, 5, tzinfo=UTC),
        repo_created_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    assert obs.description == "" and obs.topics == [] and obs.license is None
    with pytest.raises(ValidationError):
        TrendingObservation(
            repo="a/b", lane=Lane.ONPREM, stars=1,
            observed_at=datetime(2026, 7, 5, tzinfo=UTC),
            repo_created_at=datetime(2026, 7, 1, tzinfo=UTC),
            bogus=True,  # type: ignore[call-arg]
        )


def test_entry_carries_derived_fields():
    entry = TrendingEntry(
        repo="acme/rocket", lane=Lane.ONPREM, stars=1200, velocity_per_day=40.0,
        is_new=True, first_seen="2026-07-01", description="d", topics=["llm"],
    )
    assert entry.velocity_per_day == 40.0 and entry.is_new is True
    assert entry.license is None
