"""Collector construction from config."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from radar.collectors.base import BaseCollector
from radar.collectors.github import GitHubCollector
from radar.collectors.manual import ManualCollector
from radar.collectors.rss import RSSCollector
from radar.models import Config, SourceConfig, SourceType


def build_collectors(config: Config, client: Any) -> list[BaseCollector]:
    """Build one collector per enabled source type."""
    grouped: dict[SourceType, list[SourceConfig]] = defaultdict(list)
    for source in config.sources:
        if source.enabled:
            grouped[source.type].append(source)

    collectors: list[BaseCollector] = []
    if grouped[SourceType.GITHUB_REPO]:
        collectors.append(GitHubCollector(grouped[SourceType.GITHUB_REPO], client))
    if grouped[SourceType.RSS]:
        collectors.append(RSSCollector(grouped[SourceType.RSS], client))
    if grouped[SourceType.MANUAL]:
        collectors.append(ManualCollector(grouped[SourceType.MANUAL]))
    return collectors
