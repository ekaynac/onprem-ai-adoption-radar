"""Speech and audio model qualification."""

from radar.intelligence.qualifiers.base import PredicateQualifier


class AudioQualifier(PredicateQualifier):
    required_predicates = ("sample_rate",)
    fit_metrics = ("sample_rate", "streaming_support")
    risk_checks = ("language_coverage", "audio_duration_limit")
