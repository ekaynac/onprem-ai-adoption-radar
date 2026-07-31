from __future__ import annotations

from datetime import timedelta

import pytest

from radar.intelligence.contracts import ClaimFreshness
from radar.intelligence.freshness import FreshnessService

from .lifecycle_helpers import NOW


def test_all_platform_intelligence_expires_after_two_hours() -> None:
    service = FreshnessService()

    for predicate in ("security_advisory", "release_identity_new", "hardware_spec"):
        assert (
            service.status(predicate, NOW - timedelta(hours=2), NOW)
            is ClaimFreshness.FRESH
        )
        assert (
            service.status(
                predicate,
                NOW - timedelta(hours=2, seconds=1),
                NOW,
            )
            is ClaimFreshness.STALE
        )


def test_unknown_freshness_class_fails_closed() -> None:
    with pytest.raises(KeyError, match="unknown"):
        FreshnessService().status("unknown", NOW, NOW)
