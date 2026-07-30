from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from radar.intelligence.contracts import EvidenceStrength, ModelCategory
from radar.intelligence.sources.registries import (
    JsonRegistryAdapter,
    JsonRegistryConfig,
)


@pytest.mark.asyncio
async def test_json_registry_extracts_explicit_fields_without_fuzzy_matching() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "models": [
                        {
                            "id": "qwen3:32b",
                            "name": "Qwen3 32B",
                            "updated": "2026-07-30T08:00:00Z",
                            "url": "https://ollama.com/library/qwen3:32b",
                        }
                    ]
                }
            },
            request=request,
        )

    config = JsonRegistryConfig(
        id="ollama",
        url="https://registry.example/models",
        publisher_id="publisher:legacy:alibaba",
        strength=EvidenceStrength.TRUSTED_REGISTRY,
        items_path=["data", "models"],
        id_field="id",
        name_field="name",
        updated_field="updated",
        artifact_url_field="url",
        category=ModelCategory.TEXT_REASONING,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        candidates = await JsonRegistryAdapter(client, [config]).discover(
            datetime(2026, 7, 30, tzinfo=UTC)
        )

    assert candidates[0].external_id == "qwen3:32b"
    assert candidates[0].category_hint is ModelCategory.TEXT_REASONING
    assert candidates[0].source_record.strength is EvidenceStrength.TRUSTED_REGISTRY

