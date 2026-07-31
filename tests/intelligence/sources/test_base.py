from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import yaml

from radar.intelligence.contracts import EvidenceStrength
from radar.intelligence.sources.base import SourceRecord
from radar.intelligence.sources.registry import (
    SourceAdapterConfig,
    SourceRegistryConfig,
    UnknownSourceType,
    build_source_adapters,
)


NOW = datetime(2026, 7, 30, tzinfo=UTC)


def test_source_record_checksum_is_content_addressed() -> None:
    first = SourceRecord.from_bytes(
        source_id="hf",
        url="https://example.com/model",
        body=b'{"id":"x"}',
        retrieved_at=NOW,
        strength=EvidenceStrength.TRUSTED_REGISTRY,
    )
    second = SourceRecord.from_bytes(
        source_id="hf",
        url="https://example.com/model",
        body=b'{"id":"x"}',
        retrieved_at=NOW,
        strength=EvidenceStrength.TRUSTED_REGISTRY,
    )

    assert first.checksum == second.checksum == (
        "sha256:5e2b92cc57ce618dfbb54844a31775e4"
        "b95c6fb552ee6bf5a068133c12d2ad90"
    )


class FakeAdapter:
    def __init__(
        self,
        config: SourceAdapterConfig,
        client: httpx.AsyncClient,
    ):
        self.id = config.id
        self.client = client

    async def discover(self, since: datetime):
        return []

    async def fetch(self, url: str):
        raise NotImplementedError


def test_registry_returns_enabled_adapters_in_stable_id_order() -> None:
    config = SourceRegistryConfig(
        sources=[
            SourceAdapterConfig(id="z-source", type="fake"),
            SourceAdapterConfig(id="disabled", type="fake", enabled=False),
            SourceAdapterConfig(id="a-source", type="fake"),
        ]
    )
    client = httpx.AsyncClient()
    try:
        adapters = build_source_adapters(
            config,
            client,
            adapter_factories={"fake": FakeAdapter},
        )
    finally:
        import asyncio

        asyncio.run(client.aclose())

    assert [adapter.id for adapter in adapters] == ["a-source", "z-source"]


def test_registry_rejects_unknown_enabled_source_type() -> None:
    config = SourceRegistryConfig(
        sources=[SourceAdapterConfig(id="mystery", type="not-real")]
    )
    client = httpx.AsyncClient()
    try:
        with pytest.raises(UnknownSourceType, match="not-real"):
            build_source_adapters(config, client)
    finally:
        import asyncio

        asyncio.run(client.aclose())


def test_repository_source_config_builds_all_enabled_adapters() -> None:
    root = Path(__file__).resolve().parents[3]
    payload = yaml.safe_load(
        (root / "config" / "intelligence-sources.yaml").read_text(
            encoding="utf-8"
        )
    )
    config = SourceRegistryConfig.model_validate(payload)
    client = httpx.AsyncClient()
    try:
        adapters = build_source_adapters(config, client)
    finally:
        import asyncio

        asyncio.run(client.aclose())

    assert [adapter.id for adapter in adapters] == [
        "github-releases",
        "huggingface",
        "official-feeds",
    ]
