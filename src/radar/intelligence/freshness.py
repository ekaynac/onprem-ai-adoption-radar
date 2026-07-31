"""Predicate-specific freshness policy."""

from __future__ import annotations

from datetime import datetime, timedelta

from radar.intelligence.contracts import ClaimFreshness


FRESHNESS_WINDOWS = {
    "release_identity_new": timedelta(days=7),
    "release_identity_established": timedelta(days=30),
    "artifact_availability": timedelta(days=7),
    "license": timedelta(days=30),
    "platform_compatibility": timedelta(days=30),
    "benchmark": timedelta(days=90),
    "hardware_spec": timedelta(days=90),
    "security_advisory": timedelta(days=1),
    "package_release": timedelta(days=1),
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
