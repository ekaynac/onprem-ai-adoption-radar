"""Provenance-preserving intelligence source adapters."""

from radar.intelligence.sources.base import (
    DiscoveryCandidate,
    SourceAdapter,
    SourceRecord,
)
from radar.intelligence.sources.registry import (
    SourceAdapterConfig,
    SourceRegistryConfig,
    UnknownSourceType,
    build_source_adapters,
)


__all__ = [
    "DiscoveryCandidate",
    "SourceAdapter",
    "SourceAdapterConfig",
    "SourceRecord",
    "SourceRegistryConfig",
    "UnknownSourceType",
    "build_source_adapters",
]
