"""Validated construction of configured intelligence source adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import httpx
from pydantic import Field

from radar.intelligence.contracts import FrozenModel
from radar.intelligence.sources.base import SourceAdapter


class SourceAdapterConfig(FrozenModel):
    id: str
    type: str
    enabled: bool = True
    options: dict[str, Any] = Field(default_factory=dict)


class SourceRegistryConfig(FrozenModel):
    version: str = "1.0"
    sources: list[SourceAdapterConfig] = Field(default_factory=list)


class UnknownSourceType(ValueError):
    """An enabled adapter type has no registered implementation."""


AdapterFactory = Callable[
    [SourceAdapterConfig, httpx.AsyncClient],
    SourceAdapter,
]
def _build_huggingface_adapter(
    config: SourceAdapterConfig,
    client: httpx.AsyncClient,
) -> SourceAdapter:
    from radar.intelligence.sources.huggingface import HuggingFaceAdapter

    publishers = config.options.get("publishers", {})
    if not isinstance(publishers, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in publishers.items()
    ):
        raise ValueError("Hugging Face publishers must be a string mapping")
    return HuggingFaceAdapter(
        client=client,
        publishers=publishers,
        per_category_limit=int(config.options.get("per_category_limit", 100)),
        source_id=config.id,
        max_pages_per_category=int(
            config.options.get("max_pages_per_category", 20)
        ),
    )


DEFAULT_ADAPTER_FACTORIES: dict[str, AdapterFactory] = {
    "huggingface": _build_huggingface_adapter,
}


def _build_github_adapter(
    config: SourceAdapterConfig,
    client: httpx.AsyncClient,
) -> SourceAdapter:
    from radar.intelligence.sources.github import GitHubReleaseAdapter

    organizations = config.options.get("organizations", {})
    if not isinstance(organizations, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in organizations.items()
    ):
        raise ValueError("GitHub organizations must be a string mapping")
    return GitHubReleaseAdapter(
        client,
        organizations=organizations,
        source_id=config.id,
    )


def _build_feed_adapter(
    config: SourceAdapterConfig,
    client: httpx.AsyncClient,
) -> SourceAdapter:
    from radar.intelligence.sources.feeds import FeedConfig, OfficialFeedAdapter

    feeds = _validated_list(config, "feeds", FeedConfig)
    return OfficialFeedAdapter(client, feeds=feeds, source_id=config.id)


def _build_announcement_adapter(
    config: SourceAdapterConfig,
    client: httpx.AsyncClient,
) -> SourceAdapter:
    from radar.intelligence.sources.announcements import (
        AnnouncementConfig,
        AnnouncementPageAdapter,
    )

    pages = _validated_list(config, "pages", AnnouncementConfig)
    return AnnouncementPageAdapter(client, pages=pages, source_id=config.id)


def _build_json_registry_adapter(
    config: SourceAdapterConfig,
    client: httpx.AsyncClient,
) -> SourceAdapter:
    from radar.intelligence.sources.registries import (
        JsonRegistryAdapter,
        JsonRegistryConfig,
    )

    registries = _validated_list(config, "registries", JsonRegistryConfig)
    return JsonRegistryAdapter(
        client,
        registries=registries,
        source_id=config.id,
    )


def _validated_list(config: SourceAdapterConfig, key: str, model):
    raw = config.options.get(key, [])
    if not isinstance(raw, list):
        raise ValueError(f"{config.type} option {key!r} must be a list")
    return [model.model_validate(item) for item in raw]


DEFAULT_ADAPTER_FACTORIES.update(
    {
        "github_releases": _build_github_adapter,
        "official_feeds": _build_feed_adapter,
        "announcement_pages": _build_announcement_adapter,
        "json_registries": _build_json_registry_adapter,
    }
)


def build_evidence_adapters(
    config: SourceRegistryConfig,
    client: httpx.AsyncClient,
    *,
    subject_aliases: dict[str, str],
):
    from radar.intelligence.sources.evidence import (
        EvidenceAdapter,
        EvidenceSourceConfig,
    )

    adapters: list[EvidenceAdapter] = []
    for source in sorted(config.sources, key=lambda item: item.id):
        if not source.enabled or source.type != "evidence":
            continue
        sources = _validated_list(source, "sources", EvidenceSourceConfig)
        adapters.append(
            EvidenceAdapter(
                client,
                sources=sources,
                subject_aliases=subject_aliases,
                source_id=source.id,
            )
        )
    return adapters


def build_source_adapters(
    config: SourceRegistryConfig,
    client: httpx.AsyncClient,
    *,
    adapter_factories: Mapping[str, AdapterFactory] | None = None,
) -> list[SourceAdapter]:
    factories = (
        DEFAULT_ADAPTER_FACTORIES
        if adapter_factories is None
        else adapter_factories
    )
    adapters: list[SourceAdapter] = []
    for source in sorted(config.sources, key=lambda item: item.id):
        if not source.enabled:
            continue
        factory = factories.get(source.type)
        if factory is None:
            raise UnknownSourceType(
                f"Unknown intelligence source type {source.type!r} "
                f"for source {source.id!r}"
            )
        adapters.append(factory(source, client))
    return adapters
