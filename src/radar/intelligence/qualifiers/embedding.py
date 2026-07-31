"""Embedding and reranking qualification."""

from radar.intelligence.qualifiers.base import PredicateQualifier


class EmbeddingQualifier(PredicateQualifier):
    required_predicates = ("embedding_dimension",)
    fit_metrics = ("embedding_dimension", "max_sequence_length")
    risk_checks = ("normalization", "reranking_mode")
