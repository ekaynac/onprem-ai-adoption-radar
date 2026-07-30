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
