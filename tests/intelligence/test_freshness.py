from __future__ import annotations

from datetime import timedelta

import pytest

from radar.intelligence.contracts import ClaimFreshness
from radar.intelligence.freshness import FreshnessService

from .lifecycle_helpers import NOW


def test_security_advisories_expire_after_one_day() -> None:
    service = FreshnessService()

    assert (
        service.status("security_advisory", NOW - timedelta(hours=24), NOW)
        is ClaimFreshness.FRESH
    )
    assert (
        service.status(
            "security_advisory",
            NOW - timedelta(hours=24, seconds=1),
            NOW,
        )
        is ClaimFreshness.STALE
    )


def test_unknown_freshness_class_fails_closed() -> None:
    with pytest.raises(KeyError, match="unknown"):
        FreshnessService().status("unknown", NOW, NOW)
