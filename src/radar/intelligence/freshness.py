"""Predicate-specific freshness policy."""

from __future__ import annotations

from datetime import datetime, timedelta

from radar.intelligence.contracts import ClaimFreshness


PLATFORM_FRESHNESS_WINDOW = timedelta(hours=2)

# One policy across the command center: a value may remain useful after two
# hours, but it must be visibly stale until its source has been observed again.
FRESHNESS_WINDOWS = {
    predicate: PLATFORM_FRESHNESS_WINDOW
    for predicate in (
        "release_identity_new",
        "release_identity_established",
        "artifact_availability",
        "license",
        "platform_compatibility",
        "benchmark",
        "hardware_spec",
        "security_advisory",
        "package_release",
    )
}


class FreshnessService:
    def status(
        self,
        predicate_class: str,
        retrieved_at: datetime,
        now: datetime,
    ) -> ClaimFreshness:
        try:
            window = FRESHNESS_WINDOWS[predicate_class]
        except KeyError as exc:
            raise KeyError(
                f"unknown freshness predicate class: {predicate_class}"
            ) from exc
        return (
            ClaimFreshness.FRESH
            if now - retrieved_at <= window
            else ClaimFreshness.STALE
        )
