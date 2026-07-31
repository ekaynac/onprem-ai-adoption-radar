from __future__ import annotations

from datetime import timedelta

import pytest

from radar.intelligence.contracts import ClaimFreshness
from radar.intelligence.freshness import FreshnessService

from .lifecycle_helpers import NOW


@pytest.mark.parametrize(
    ("predicate", "window"),
    [
        ("release_identity_new", timedelta(days=7)),
        ("release_identity_established", timedelta(days=30)),
        ("artifact_availability", timedelta(days=7)),
        ("license", timedelta(days=30)),
        ("platform_compatibility", timedelta(days=30)),
        ("benchmark", timedelta(days=90)),
        ("hardware_spec", timedelta(days=90)),
        ("security_advisory", timedelta(days=1)),
        ("package_release", timedelta(days=1)),
    ],
)
def test_predicate_freshness_boundary(
    predicate: str,
    window: timedelta,
) -> None:
    service = FreshnessService()

    assert service.status(predicate, NOW - window, NOW) is ClaimFreshness.FRESH
    assert (
        service.status(
            predicate,
            NOW - window - timedelta(seconds=1),
            NOW,
        )
        is ClaimFreshness.STALE
    )


def test_unknown_freshness_class_fails_closed() -> None:
    with pytest.raises(KeyError, match="unknown"):
        FreshnessService().status("unknown", NOW, NOW)
