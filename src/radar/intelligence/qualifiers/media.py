"""Image and video generation qualification."""

from radar.intelligence.qualifiers.base import PredicateQualifier


class MediaQualifier(PredicateQualifier):
    required_predicates = ("native_resolution",)
    fit_metrics = ("native_resolution", "memory_gb")
    risk_checks = ("content_policy", "scheduler_support")
