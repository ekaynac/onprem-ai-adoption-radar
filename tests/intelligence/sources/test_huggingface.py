from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from radar.intelligence.contracts import EvidenceStrength, ModelCategory
from radar.intelligence.sources.huggingface import (
    HF_PIPELINE_CATEGORIES,
    HuggingFaceAdapter,
)


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "intelligence"
NOW = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def discovery_client() -> httpx.AsyncClient:
    items = {
        "image-text-to-text": load_fixture("hf_kimi_k3.json"),
        "feature-extraction": load_fixture("hf_embedding.json"),
        "automatic-speech-recognition": load_fixture("hf_speech.json"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        pipeline = request.url.params.get("pipeline_tag")
        assert request.url.params.get("config") == "true"
        payload = [items[pipeline]] if pipeline in items else []
        return httpx.Response(200, json=payload, request=request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_discovers_new_official_multimodal_release() -> None:
    async with discovery_client() as client:
        adapter = HuggingFaceAdapter(
            client=client,
            publishers={"moonshotai": "publisher:moonshot-ai"},
            clock=lambda: NOW,
        )

        candidates = await adapter.discover(
            datetime(2026, 7, 30, tzinfo=UTC)
        )

    kimi = next(
        candidate
        for candidate in candidates
        if candidate.external_id == "moonshotai/Kimi-K3"
    )
    assert kimi.publisher_hint == "publisher:moonshot-ai"
    assert kimi.category_hint is ModelCategory.MULTIMODAL
    assert kimi.source_record.strength is EvidenceStrength.TRUSTED_REGISTRY
    assert kimi.claims["params_total"] == 1_000_000_000_000
    assert "https://huggingface.co/moonshotai/Kimi-K3" in kimi.artifact_urls


@pytest.mark.asyncio
async def test_discovers_all_recent_categories_and_marks_unknown_publishers() -> None:
    async with discovery_client() as client:
        adapter = HuggingFaceAdapter(client=client, publishers={}, clock=lambda: NOW)

        candidates = await adapter.discover(
            datetime(2026, 7, 30, tzinfo=UTC)
        )

    by_id = {candidate.external_id: candidate for candidate in candidates}
    assert by_id["acme/Embed-v2"].category_hint is ModelCategory.EMBEDDING_RERANKING
    assert by_id["acme/Speech-v1"].category_hint is ModelCategory.SPEECH_AUDIO
    assert by_id["acme/Embed-v2"].publisher_hint == "provisional:acme"
    assert by_id["acme/Speech-v1"].claims["gated"] is True


@pytest.mark.asyncio
async def test_discovery_follows_cursor_until_page_is_older_than_cutoff() -> None:
    recent = {
        **load_fixture("hf_kimi_k3.json"),
        "id": "acme/Recent-Text",
        "pipeline_tag": "text-generation",
    }
    stale = {
        **recent,
        "id": "acme/Stale-Text",
        "lastModified": "2026-07-29T23:59:59.000Z",
    }
    text_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal text_requests
        if request.url.params.get("pipeline_tag") != "text-generation":
            return httpx.Response(200, json=[], request=request)
        text_requests += 1
        if request.url.params.get("cursor") == "page-2":
            return httpx.Response(
                200,
                json=[stale],
                headers={
                    "Link": (
                        "<https://huggingface.co/api/models?"
                        "pipeline_tag=text-generation&cursor=page-3>; rel=\"next\""
                    )
                },
                request=request,
            )
        return httpx.Response(
            200,
            json=[recent],
            headers={
                "Link": (
                    "<https://huggingface.co/api/models?"
                    "pipeline_tag=text-generation&cursor=page-2>; rel=\"next\""
                )
            },
            request=request,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        adapter = HuggingFaceAdapter(client=client, publishers={}, clock=lambda: NOW)
        candidates = await adapter.discover(
            datetime(2026, 7, 30, tzinfo=UTC)
        )

    assert text_requests == 2
    assert [candidate.external_id for candidate in candidates] == [
        "acme/Recent-Text"
    ]


def test_every_supported_pipeline_maps_to_category() -> None:
    expected = {
        "text-generation": ModelCategory.TEXT_REASONING,
        "image-text-to-text": ModelCategory.MULTIMODAL,
        "feature-extraction": ModelCategory.EMBEDDING_RERANKING,
        "automatic-speech-recognition": ModelCategory.SPEECH_AUDIO,
        "text-to-speech": ModelCategory.SPEECH_AUDIO,
        "text-to-image": ModelCategory.IMAGE_VIDEO,
        "text-to-video": ModelCategory.IMAGE_VIDEO,
        "image-to-text": ModelCategory.VISION_DOCUMENT,
        "document-question-answering": ModelCategory.VISION_DOCUMENT,
    }
    assert expected == HF_PIPELINE_CATEGORIES


@pytest.mark.asyncio
async def test_enrichment_keeps_metadata_config_and_card_as_separate_evidence() -> None:
    metadata = load_fixture("hf_kimi_k3.json")
    config = {
        "num_hidden_layers": 80,
        "hidden_size": 8192,
        "max_position_embeddings": 262144,
        "num_attention_heads": 64,
        "num_key_value_heads": 8,
        "quantization_config": {"quant_method": "fp8"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/api/models/"):
            return httpx.Response(200, json=metadata, request=request)
        if request.url.path.endswith("/config.json"):
            return httpx.Response(200, json=config, request=request)
        if request.url.path.endswith("/README.md"):
            return httpx.Response(200, text="# Kimi K3", request=request)
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        adapter = HuggingFaceAdapter(client=client, publishers={}, clock=lambda: NOW)
        enrichment = await adapter.enrich("moonshotai/Kimi-K3")

    assert {record.kind for record in enrichment.records} >= {
        "metadata",
        "config",
        "model_card",
        "siblings",
        "safetensors",
        "gating",
        "license",
        "quantization",
    }
    assert enrichment.claims["num_layers"] == 80
    assert enrichment.claims["context_length"] == 262144
    assert enrichment.claims["quantization_format"] == "FP8"
    assert enrichment.claims["architecture"]["attention_kind"] == "gqa"
