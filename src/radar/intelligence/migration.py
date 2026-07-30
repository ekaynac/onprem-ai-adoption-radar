"""Idempotent import of legacy YAML and JSONL state."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from radar.intelligence.contracts import (
    Claim,
    ClaimState,
    EvidenceObservation,
    EvidenceStrength,
    LifecycleState,
    ModelCategory,
    ProductFamily,
    Publisher,
    Release,
    ReleaseLane,
)
from radar.models_radar.entities import Modality, ModelSeed, Openness
from radar.models_radar.history import load_model_events
from radar.models_radar.platform_matrix import PlatformSeed, load_platform_matrix
from radar.models_radar.seed import load_model_seed


LEGACY_OBSERVED_AT = datetime(2000, 1, 1, tzinfo=UTC)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class MigrationReport:
    models_imported: int
    platforms_imported: int
    history_events_imported: int
    already_present: int
    warnings: tuple[str, ...]


def _slug(value: str) -> str:
    return _SLUG_RE.sub("-", value.casefold()).strip("-")


def _checksum(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _model_category(seed: ModelSeed) -> ModelCategory:
    if seed.modality is Modality.AUDIO:
        return ModelCategory.SPEECH_AUDIO
    if seed.modality in {Modality.VISION, Modality.MULTIMODAL}:
        return ModelCategory.MULTIMODAL
    return ModelCategory.TEXT_REASONING


def _release_lane(seed: ModelSeed) -> ReleaseLane:
    if seed.openness is Openness.OPEN_PERMISSIVE:
        return ReleaseLane.DEPLOYABLE
    if seed.openness is Openness.CLOSED:
        return ReleaseLane.MARKET_REFERENCE
    return ReleaseLane.ADJACENT


def _first_observed_at(seed: ModelSeed) -> datetime:
    value = seed.release_date
    if not value:
        return LEGACY_OBSERVED_AT
    try:
        if len(value) == 7:
            value = f"{value}-01"
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    except ValueError:
        return LEGACY_OBSERVED_AT


def _publisher_name(seed: ModelSeed) -> str:
    fallback = (seed.hf_repo or "legacy").split("/", 1)[0]
    return seed.backer.name if seed.backer else fallback


def _publisher_catalog(models: list[ModelSeed]) -> dict[str, Publisher]:
    aliases_by_id: dict[str, set[str]] = {}
    for seed in models:
        name = _publisher_name(seed)
        publisher_id = f"publisher:legacy:{_slug(name)}"
        aliases_by_id.setdefault(publisher_id, set()).add(name)

    publishers: dict[str, Publisher] = {}
    for publisher_id, names in aliases_by_id.items():
        aliases = sorted(names, key=lambda value: (value.casefold(), value))
        publishers[publisher_id] = Publisher(
            id=publisher_id,
            name=aliases[0],
            official_domains=[],
            official_accounts=[],
            aliases=aliases,
        )
    return publishers


def _claim_values(seed: ModelSeed) -> dict[str, Any]:
    fields = (
        "params_total",
        "params_active",
        "num_layers",
        "hidden_size",
        "context_length",
        "license",
        "openness",
        "release_date",
        "use_case",
        "architecture",
    )
    values: dict[str, Any] = {}
    payload = seed.model_dump(mode="json")
    for field in fields:
        if payload.get(field) is not None:
            values[field] = payload[field]
    if seed.hf_repo:
        values["hf_repo"] = seed.hf_repo
    if seed.ollama_name:
        values["ollama_name"] = seed.ollama_name
    return values


def _import_model(seed: ModelSeed, publisher: Publisher, repository) -> bool:
    repository.upsert_publisher(publisher)
    family = ProductFamily(
        id=f"family:legacy:{_slug(publisher.name)}:{_slug(seed.family)}",
        publisher_id=publisher.id,
        name=seed.family,
        aliases=[seed.family],
    )
    repository.upsert_family(family)
    release_id = f"release:legacy:{seed.id}"
    created = repository.upsert_release(
        Release(
            id=release_id,
            family_id=family.id,
            publisher_id=publisher.id,
            name=seed.name,
            category=_model_category(seed),
            lane=_release_lane(seed),
            lifecycle=(
                LifecycleState.VERIFIED
                if seed.spec_verified
                else LifecycleState.DETECTED
            ),
            first_observed_at=_first_observed_at(seed),
            discovery_evidence_strength=EvidenceStrength.TRUSTED_REGISTRY,
        )
    )
    seed_payload = seed.model_dump(mode="json")
    evidence = EvidenceObservation(
        id=f"evidence:legacy:model-seed:{seed.id}",
        source_url=(
            f"https://huggingface.co/{seed.hf_repo}"
            if seed.hf_repo
            else "config/model-seed.yaml"
        ),
        strength=EvidenceStrength.TRUSTED_REGISTRY,
        retrieved_at=LEGACY_OBSERVED_AT,
        checksum=_checksum(seed_payload),
        extractor_version="legacy-model-seed-v1",
    )
    repository.append_evidence(evidence)
    claim_state = ClaimState.VERIFIED if seed.spec_verified else ClaimState.CANDIDATE
    for predicate, value in sorted(_claim_values(seed).items()):
        repository.append_claim(
            Claim(
                id=f"claim:legacy:{seed.id}:{predicate}",
                subject_id=release_id,
                predicate=predicate,
                value=value,
                state=claim_state,
                observed_at=LEGACY_OBSERVED_AT,
                evidence_ids=[evidence.id],
            )
        )
    return created


def _import_platform(seed: PlatformSeed, repository) -> bool:
    payload = seed.model_dump(mode="json")
    platform_id = f"platform:legacy:{seed.id}"
    created = repository.import_platform(
        platform_id=platform_id,
        name=seed.name,
        repo_url=seed.repo_url,
        verified_at=seed.verified,
        payload=payload,
    )
    evidence = EvidenceObservation(
        id=f"evidence:legacy:platform:{seed.id}",
        source_url=seed.sources[0],
        strength=EvidenceStrength.OFFICIAL_DOCUMENTATION,
        retrieved_at=datetime.fromisoformat(seed.verified).replace(tzinfo=UTC),
        checksum=_checksum(payload),
        extractor_version="legacy-platform-seed-v1",
    )
    repository.append_evidence(evidence)
    for scope, values in (("hardware", seed.hardware), ("feature", seed.features)):
        for key, value in sorted(values.items()):
            repository.append_claim(
                Claim(
                    id=f"claim:legacy:platform:{seed.id}:{scope}:{key}",
                    subject_id=platform_id,
                    predicate=f"{scope}.{key}",
                    value=value,
                    state=ClaimState.VERIFIED,
                    observed_at=evidence.retrieved_at,
                    evidence_ids=[evidence.id],
                )
            )
    return created


def _import_model_history(path: Path, repository) -> tuple[int, int]:
    imported = 0
    present = 0
    for event in load_model_events(path):
        payload = event.model_dump(mode="json")
        event_hash = _checksum(payload).removeprefix("sha256:")
        created = repository.append_legacy_event(
            event_id=f"legacy:model-history:{event_hash}",
            kind="model_history",
            subject_id=f"release:legacy:{event.model_id}",
            observed_at=event.observed_at,
            payload=payload,
        )
        imported += int(created)
        present += int(not created)
    return imported, present


def import_legacy_state(root: Path, repository) -> MigrationReport:
    models = load_model_seed(root / "config" / "model-seed.yaml")
    platforms = load_platform_matrix(root / "config" / "platform-matrix.yaml")
    publishers = _publisher_catalog(models)
    models_imported = 0
    platforms_imported = 0
    already_present = 0

    for seed in models:
        publisher_id = f"publisher:legacy:{_slug(_publisher_name(seed))}"
        created = _import_model(seed, publishers[publisher_id], repository)
        models_imported += int(created)
        already_present += int(not created)
    for platform in platforms:
        created = _import_platform(platform, repository)
        platforms_imported += int(created)
        already_present += int(not created)
    history_imported, history_present = _import_model_history(
        root / "data" / "model-history.jsonl", repository
    )
    already_present += history_present
    return MigrationReport(
        models_imported=models_imported,
        platforms_imported=platforms_imported,
        history_events_imported=history_imported,
        already_present=already_present,
        warnings=(),
    )
