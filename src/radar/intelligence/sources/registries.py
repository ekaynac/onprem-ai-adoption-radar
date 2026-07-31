"""Schema-driven discovery for model and deployment registries."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import Field

from radar.intelligence.contracts import (
    EvidenceStrength,
    FrozenModel,
    ModelCategory,
)
from radar.intelligence.sources.base import DiscoveryCandidate, SourceRecord
from radar.intelligence.sources.utils import parse_datetime


class JsonRegistryConfig(FrozenModel):
    id: str
    url: str
    publisher_id: str | None = None
    strength: EvidenceStrength
    items_path: list[str] = Field(default_factory=list)
    id_field: str
    name_field: str
    updated_field: str
    artifact_url_field: str
    category: ModelCategory | None = None
    enabled: bool = True


class JsonRegistryAdapter:
    id = "json-registries"

    def __init__(
        self,
        client: httpx.AsyncClient,
        registries: list[JsonRegistryConfig],
        *,
        source_id: str = "json-registries",
        clock: Callable[[], datetime] | None = None,
    ):
        self.client = client
        self.registries = registries
        self.id = source_id
        self.clock = clock or (lambda: datetime.now(UTC))

    async def discover(self, since: datetime) -> list[DiscoveryCandidate]:
        candidates: list[DiscoveryCandidate] = []
        for config in sorted(self.registries, key=lambda item: item.id):
            if not config.enabled:
                continue
            response = await self.client.get(config.url)
            response.raise_for_status()
            record = SourceRecord.from_bytes(
                source_id=self.id,
                url=str(response.request.url),
                body=response.content,
                retrieved_at=self.clock(),
                strength=config.strength,
                content_type=response.headers.get("content-type"),
            )
            items = _path(response.json(), config.items_path)
            if not isinstance(items, list):
                raise ValueError(
                    f"Registry {config.id!r} items path did not resolve to a list"
                )
            for item in items:
                if not isinstance(item, dict):
                    continue
                updated_at = parse_datetime(item.get(config.updated_field))
                if updated_at is None or updated_at < since:
                    continue
                external_id = str(item[config.id_field])
                owner = external_id.split("/", 1)[0].split(":", 1)[0]
                candidates.append(
                    DiscoveryCandidate(
                        source_record=record,
                        external_id=external_id,
                        publisher_hint=(
                            config.publisher_id
                            or f"provisional:{owner.casefold()}"
                        ),
                        release_name=str(item[config.name_field]),
                        category_hint=config.category,
                        artifact_urls=[
                            str(item[config.artifact_url_field])
                        ],
                        claims={
                            **item,
                            "registry_updated_at": updated_at.isoformat(),
                        },
                    )
                )
        return sorted(
            candidates,
            key=lambda candidate: candidate.external_id.casefold(),
        )

    async def fetch(self, url: str) -> SourceRecord:
        response = await self.client.get(url)
        response.raise_for_status()
        return SourceRecord.from_bytes(
            source_id=self.id,
            url=str(response.request.url),
            body=response.content,
            retrieved_at=self.clock(),
            strength=EvidenceStrength.TRUSTED_REGISTRY,
            content_type=response.headers.get("content-type"),
        )


def _path(value: Any, fields: list[str]) -> Any:
    current = value
    for field in fields:
        if not isinstance(current, dict) or field not in current:
            return None
        current = current[field]
    return current
