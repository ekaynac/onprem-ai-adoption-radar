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
    sources: list[SourceAdapterConfig] = Field(default_factory=list)


class UnknownSourceType(ValueError):
    """An enabled adapter type has no registered implementation."""


AdapterFactory = Callable[
    [SourceAdapterConfig, httpx.AsyncClient],
    SourceAdapter,
]
DEFAULT_ADAPTER_FACTORIES: dict[str, AdapterFactory] = {}


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
