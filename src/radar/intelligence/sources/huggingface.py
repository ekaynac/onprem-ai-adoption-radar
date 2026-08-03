"""Comprehensive Hugging Face release discovery and enrichment."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import Field

from radar.intelligence.contracts import (
    EvidenceStrength,
    FrozenModel,
    ModelCategory,
)
from radar.intelligence.sources.base import DiscoveryCandidate, SourceRecord
from radar.models_radar.hf_config import parse_architecture, parse_quant_format


HF_API_URL = "https://huggingface.co/api/models"
LINEAGE_TAG_PREFIX = "base_model:"
LINEAGE_TAG_RELATIONS = frozenset({"finetune", "quantized", "merge", "adapter"})
HF_PIPELINE_CATEGORIES = {
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


class HFEnrichmentRecord(FrozenModel):
    kind: str
    source_record: SourceRecord


class HFEnrichment(FrozenModel):
    repo_id: str
    records: list[HFEnrichmentRecord]
    claims: dict[str, Any]
    artifact_urls: list[str] = Field(default_factory=list)


class HuggingFaceAdapter:
    id = "huggingface"

    def __init__(
        self,
        client: httpx.AsyncClient,
        publishers: dict[str, str],
        per_category_limit: int = 100,
        *,
        source_id: str = "huggingface",
        max_pages_per_category: int = 20,
        clock: Callable[[], datetime] | None = None,
    ):
        self.client = client
        self.publishers = {
            handle.casefold(): publisher_id
            for handle, publisher_id in publishers.items()
        }
        self.per_category_limit = per_category_limit
        self.id = source_id
        self.max_pages_per_category = max_pages_per_category
        self.clock = clock or (lambda: datetime.now(UTC))

    async def discover(self, since: datetime) -> list[DiscoveryCandidate]:
        candidates: dict[str, DiscoveryCandidate] = {}
        for pipeline_tag, category in HF_PIPELINE_CATEGORIES.items():
            url: str | None = HF_API_URL
            params: dict[str, Any] | None = {
                "pipeline_tag": pipeline_tag,
                "sort": "lastModified",
                "direction": -1,
                "limit": self.per_category_limit,
                "full": True,
                "cardData": True,
                "config": True,
            }
            for _page in range(self.max_pages_per_category):
                if url is None:
                    break
                response = await self.client.get(url, params=params)
                response.raise_for_status()
                record = self._record_from_response(response)
                items = response.json()
                if not isinstance(items, list):
                    raise ValueError("Hugging Face model listing must be a JSON list")

                saw_recent = False
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    modified = _parse_datetime(item.get("lastModified"))
                    if modified is None or modified < since:
                        continue
                    saw_recent = True
                    candidate = self._candidate(item, record, category)
                    candidates.setdefault(
                        candidate.external_id.casefold(),
                        candidate,
                    )
                if items and not saw_recent and all(
                    _parse_datetime(item.get("lastModified")) is not None
                    for item in items
                    if isinstance(item, dict)
                ):
                    break
                next_link = response.links.get("next")
                url = next_link.get("url") if next_link is not None else None
                params = None
        return [candidates[key] for key in sorted(candidates)]

    async def fetch(self, url: str) -> SourceRecord:
        response = await self.client.get(url)
        response.raise_for_status()
        return self._record_from_response(response)

    async def enrich(self, repo_id: str) -> HFEnrichment:
        encoded_repo = quote(repo_id, safe="/")
        metadata_response = await self.client.get(f"{HF_API_URL}/{encoded_repo}")
        metadata_response.raise_for_status()
        metadata = metadata_response.json()
        if not isinstance(metadata, dict):
            raise ValueError("Hugging Face model metadata must be a JSON object")

        config_url = (
            f"https://huggingface.co/{encoded_repo}/resolve/main/config.json"
        )
        config_response = await self.client.get(config_url)
        config_response.raise_for_status()
        config = config_response.json()
        if not isinstance(config, dict):
            config = {}

        records = [
            HFEnrichmentRecord(
                kind="metadata",
                source_record=self._record_from_response(metadata_response),
            ),
            HFEnrichmentRecord(
                kind="config",
                source_record=self._record_from_response(config_response),
            ),
        ]
        records.extend(
            self._metadata_slices(
                repo_id,
                metadata,
                config,
            )
        )

        card_url = f"https://huggingface.co/{encoded_repo}/resolve/main/README.md"
        card_response = await self.client.get(card_url)
        if card_response.status_code < 400:
            records.append(
                HFEnrichmentRecord(
                    kind="model_card",
                    source_record=self._record_from_response(card_response),
                )
            )

        api_base_models: Any = None
        base_models_response = await self.client.get(
            f"{HF_API_URL}/{encoded_repo}",
            params={"expand": ["baseModels"]},
        )
        if base_models_response.status_code < 400:
            payload = base_models_response.json()
            if isinstance(payload, dict):
                api_base_models = payload.get("baseModels")
            records.append(
                HFEnrichmentRecord(
                    kind="base_models",
                    source_record=self._record_from_response(
                        base_models_response
                    ),
                )
            )

        siblings = _sibling_names(metadata)
        artifact_urls = [f"https://huggingface.co/{repo_id}"]
        artifact_urls.extend(
            f"https://huggingface.co/{repo_id}/resolve/main/{name}"
            for name in siblings
        )
        return HFEnrichment(
            repo_id=repo_id,
            records=records,
            claims=_enrichment_claims(metadata, config, api_base_models),
            artifact_urls=artifact_urls,
        )

    def _candidate(
        self,
        item: dict[str, Any],
        record: SourceRecord,
        category: ModelCategory,
    ) -> DiscoveryCandidate:
        repo_id = str(item["id"])
        owner, _, release_name = repo_id.partition("/")
        if not release_name:
            release_name = owner
        publisher_hint = self.publishers.get(
            owner.casefold(),
            f"provisional:{owner.casefold()}",
        )
        siblings = _sibling_names(item)
        artifact_urls = [f"https://huggingface.co/{repo_id}"]
        artifact_urls.extend(
            f"https://huggingface.co/{repo_id}/resolve/main/{name}"
            for name in siblings
            if name.endswith((".gguf", ".safetensors", "config.json"))
        )
        return DiscoveryCandidate(
            source_record=record,
            external_id=repo_id,
            publisher_hint=publisher_hint,
            release_name=release_name,
            category_hint=category,
            artifact_urls=artifact_urls,
            claims=_metadata_claims(item),
        )

    def _record_from_response(self, response: httpx.Response) -> SourceRecord:
        return SourceRecord.from_bytes(
            source_id=self.id,
            url=str(response.request.url),
            body=response.content,
            retrieved_at=self.clock(),
            strength=EvidenceStrength.TRUSTED_REGISTRY,
            content_type=response.headers.get("content-type"),
        )

    def _metadata_slices(
        self,
        repo_id: str,
        metadata: dict[str, Any],
        config: dict[str, Any],
    ) -> list[HFEnrichmentRecord]:
        slices = {
            "siblings": metadata.get("siblings") or [],
            "safetensors": metadata.get("safetensors") or {},
            "gating": {"gated": bool(metadata.get("gated"))},
            "license": {
                "license": (metadata.get("cardData") or {}).get("license")
                or metadata.get("license")
            },
            "quantization": config.get("quantization_config") or {},
        }
        return [
            HFEnrichmentRecord(
                kind=kind,
                source_record=SourceRecord.from_bytes(
                    source_id=self.id,
                    url=f"https://huggingface.co/{repo_id}#evidence-{kind}",
                    body=_canonical_json(value),
                    retrieved_at=self.clock(),
                    strength=EvidenceStrength.TRUSTED_REGISTRY,
                    content_type="application/json",
                ),
            )
            for kind, value in slices.items()
        ]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC)


def _sibling_names(metadata: dict[str, Any]) -> list[str]:
    return sorted(
        {
            str(sibling["rfilename"])
            for sibling in metadata.get("siblings") or []
            if isinstance(sibling, dict) and sibling.get("rfilename")
        }
    )


def _lineage_entries_from_metadata(
    metadata: dict[str, Any],
) -> list[tuple[Any, str | None, str]]:
    entries: list[tuple[Any, str | None, str]] = []
    tags = metadata.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            if not isinstance(tag, str) or not tag.startswith(
                LINEAGE_TAG_PREFIX
            ):
                continue
            rest = tag[len(LINEAGE_TAG_PREFIX) :]
            head, _, tail = rest.partition(":")
            if head in LINEAGE_TAG_RELATIONS and tail:
                entries.append((tail, head, "tags"))
            else:
                entries.append((rest, None, "tags"))
    card = metadata.get("cardData")
    if isinstance(card, dict):
        declared = card.get("base_model")
        relation_value = card.get("base_model_relation")
        relation = (
            relation_value if isinstance(relation_value, str) else None
        )
        parents = declared if isinstance(declared, list) else [declared]
        entries.extend((parent, relation, "card") for parent in parents)
    return entries


def _lineage_entries_from_api(
    payload: Any,
) -> list[tuple[Any, str | None, str]]:
    groups = payload if isinstance(payload, list) else [payload]
    entries: list[tuple[Any, str | None, str]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        relation_value = group.get("relation")
        relation = (
            relation_value if isinstance(relation_value, str) else None
        )
        for model in group.get("models") or []:
            parent = model.get("id") if isinstance(model, dict) else model
            entries.append((parent, relation, "api"))
    return entries


def _normalize_lineage(
    entries: list[tuple[Any, str | None, str]],
    repo_id: Any,
) -> list[dict[str, Any]]:
    """Dedupe declared parents; a relation-qualified entry beats a bare one.

    Entry order encodes source priority (feed authoritative sources first);
    the first entry for a given (parent, relation) wins.
    """
    by_key: dict[tuple[str, str | None], dict[str, Any]] = {}
    for parent, relation, via in entries:
        if not isinstance(parent, str):
            continue
        parent = parent.strip()
        if "/" not in parent or not parent or parent == repo_id:
            continue
        by_key.setdefault(
            (parent.casefold(), relation),
            {"parent_repo": parent, "relation": relation, "via": via},
        )
    by_parent: dict[str, list[dict[str, Any]]] = {}
    for (parent_key, _), entry in by_key.items():
        by_parent.setdefault(parent_key, []).append(entry)
    collapsed: list[dict[str, Any]] = []
    for parent_key in sorted(by_parent):
        group = by_parent[parent_key]
        qualified = [entry for entry in group if entry["relation"]]
        collapsed.extend(
            sorted(
                qualified or group[:1],
                key=lambda entry: entry["relation"] or "",
            )
        )
    return collapsed


def _metadata_claims(metadata: dict[str, Any]) -> dict[str, Any]:
    card = metadata.get("cardData")
    if not isinstance(card, dict):
        card = {}
    safetensors = metadata.get("safetensors")
    if not isinstance(safetensors, dict):
        safetensors = {}
    values = {
        "repo_id": metadata.get("id"),
        "pipeline_tag": metadata.get("pipeline_tag"),
        "library_name": metadata.get("library_name")
        or card.get("library_name"),
        "last_modified": metadata.get("lastModified"),
        "sha": metadata.get("sha"),
        "downloads": metadata.get("downloads"),
        "likes": metadata.get("likes"),
        "gated": bool(metadata.get("gated")),
        "license": card.get("license") or metadata.get("license"),
        "params_total": safetensors.get("total"),
        "lineage_declared": _normalize_lineage(
            _lineage_entries_from_metadata(metadata),
            metadata.get("id"),
        )
        or None,
    }
    return {key: value for key, value in values.items() if value is not None}


def _enrichment_claims(
    metadata: dict[str, Any],
    config: dict[str, Any],
    api_base_models: Any = None,
) -> dict[str, Any]:
    claims = _metadata_claims(metadata)
    lineage = _normalize_lineage(
        _lineage_entries_from_api(api_base_models)
        + _lineage_entries_from_metadata(metadata),
        metadata.get("id"),
    )
    if lineage:
        claims["lineage_declared"] = lineage
    else:
        claims.pop("lineage_declared", None)
    architecture = parse_architecture(config)
    claims.update(
        {
            "num_layers": config.get("num_hidden_layers"),
            "hidden_size": config.get("hidden_size"),
            "context_length": config.get("max_position_embeddings"),
            "architecture": architecture.model_dump(mode="json"),
            "quantization_format": parse_quant_format(config),
            "quantization_config": config.get("quantization_config"),
            "siblings": _sibling_names(metadata),
        }
    )
    return {
        key: value
        for key, value in claims.items()
        if value is not None
    }
