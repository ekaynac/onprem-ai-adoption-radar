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
    LifecycleTransition,
    ModelCategory,
    ProductFamily,
    Publisher,
    Release,
    ReleaseLane,
)
from radar.intelligence.lifecycle import LifecycleService
from radar.models_radar.entities import Modality, ModelSeed, Openness
from radar.models_radar.history import load_model_events
from radar.models_radar.platform_matrix import PlatformSeed, load_platform_matrix
from radar.models_radar.seed import load_model_seed


LEGACY_OBSERVED_AT = datetime(2000, 1, 1, tzinfo=UTC)
_SLUG_RE = re.compile(r"[^a-z0-9]+")
SOURCE_PUBLISHERS = (
    Publisher(
        id="publisher:moonshot-ai",
        name="Moonshot AI",
        official_domains=["moonshot.ai"],
        official_accounts=["moonshotai"],
        aliases=["Moonshot", "Kimi"],
    ),
    Publisher(
        id="publisher:platform:llama-cpp",
        name="llama.cpp",
        official_domains=["github.com"],
        official_accounts=["ggml-org"],
        aliases=["llama-cpp", "ggml-org"],
    ),
    Publisher(
        id="publisher:platform:ollama",
        name="Ollama",
        official_domains=["ollama.com"],
        official_accounts=["ollama"],
        aliases=["ollama"],
    ),
    Publisher(
        id="publisher:platform:vllm",
        name="vLLM",
        official_domains=["vllm.ai"],
        official_accounts=["vllm-project"],
        aliases=["vllm"],
    ),
)


@dataclass(frozen=True)
class MigrationReport:
    models_imported: int
    platforms_imported: int
    history_events_imported: int
    already_present: int
    warnings: tuple[str, ...]
    volatile_reviews_amnestied: int = 0


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
    existing = next(
        (
            release
            for release in repository.list_all_releases()
            if release.id == release_id
        ),
        None,
    )
    created = repository.upsert_release(
        existing
        or Release(
            id=release_id,
            family_id=family.id,
            publisher_id=publisher.id,
            name=seed.name,
            category=_model_category(seed),
            lane=_release_lane(seed),
            lifecycle=LifecycleState.DETECTED,
            first_observed_at=_first_observed_at(seed),
            discovery_evidence_strength=EvidenceStrength.TRUSTED_REGISTRY,
        )
    )
    seed_payload = seed.model_dump(mode="json")
    evidence_checksum = _checksum(seed_payload)
    evidence_id = f"evidence:legacy:model-seed:{seed.id}"
    existing_evidence = repository.get_evidence(evidence_id)
    if (
        existing_evidence is not None
        and existing_evidence.checksum != evidence_checksum
    ):
        # The curated seed evolved (evidence is immutable, seeds are not):
        # append a content-addressed row instead of conflicting with the
        # historical one — same pattern as the platform import.
        evidence_id = f"{evidence_id}:{evidence_checksum.removeprefix('sha256:')[:16]}"
    evidence = EvidenceObservation(
        id=evidence_id,
        source_url=(
            f"https://huggingface.co/{seed.hf_repo}"
            if seed.hf_repo
            else "config/model-seed.yaml"
        ),
        strength=EvidenceStrength.TRUSTED_REGISTRY,
        retrieved_at=LEGACY_OBSERVED_AT,
        checksum=evidence_checksum,
        extractor_version="legacy-model-seed-v1",
    )
    repository.append_evidence(evidence)
    claim_state = ClaimState.VERIFIED if seed.spec_verified else ClaimState.CANDIDATE
    for predicate, value in sorted(_claim_values(seed).items()):
        claim = Claim(
            id=f"claim:legacy:{seed.id}:{predicate}",
            subject_id=release_id,
            predicate=predicate,
            value=value,
            state=claim_state,
            observed_at=LEGACY_OBSERVED_AT,
            evidence_ids=[evidence.id],
        )
        existing_claim = repository.get_claim(claim.id)
        if existing_claim is not None and (
            existing_claim.subject_id == claim.subject_id
            and existing_claim.predicate == claim.predicate
            and existing_claim.value == claim.value
            and existing_claim.unit == claim.unit
        ):
            # Verification and freshness jobs may advance state/time, and a
            # seed edit re-addresses the evidence id. Re-import must preserve
            # the stored claim rather than conflicting over those fields.
            continue
        repository.append_claim(claim)
    current = repository.get_release_required(release_id)
    if seed.spec_verified:
        reason = "Legacy seed carries human-verified specifications"
        if current.lifecycle is LifecycleState.DETECTED:
            LifecycleService(repository).transition(
                release_id,
                LifecycleState.VERIFIED,
                reason=reason,
                evidence_ids=[evidence.id],
                now=LEGACY_OBSERVED_AT,
            )
        elif not any(
            transition.from_state is LifecycleState.DETECTED
            and transition.to_state is LifecycleState.VERIFIED
            for transition in repository.list_lifecycle_transitions(release_id)
        ):
            # Early migrations projected verified state directly. Preserve that
            # projection while repairing the missing auditable history entry.
            repository.append_lifecycle_transition(
                LifecycleTransition(
                    release_id=release_id,
                    from_state=LifecycleState.DETECTED,
                    to_state=LifecycleState.VERIFIED,
                    observed_at=LEGACY_OBSERVED_AT,
                    reason=reason,
                    evidence_ids=[evidence.id],
                )
            )
    return created


def _import_platform(seed: PlatformSeed, repository) -> bool:
    payload = seed.model_dump(mode="json")
    platform_id = f"platform:legacy:{seed.id}"
    created, metadata_updated = repository.reconcile_legacy_platform_metadata(
        platform_id=platform_id,
        name=seed.name,
        repo_url=seed.repo_url,
        verified_at=seed.verified,
        payload=payload,
    )
    evidence_checksum = _checksum(payload)
    evidence_id = f"evidence:legacy:platform:{seed.id}"
    existing_evidence = repository.get_evidence(evidence_id)
    if existing_evidence is not None and (
        existing_evidence.source_url != seed.sources[0]
        or existing_evidence.checksum != evidence_checksum
    ):
        evidence_id = f"{evidence_id}:{evidence_checksum[:16]}"
    evidence = EvidenceObservation(
        id=evidence_id,
        source_url=seed.sources[0],
        strength=EvidenceStrength.OFFICIAL_DOCUMENTATION,
        retrieved_at=datetime.fromisoformat(seed.verified).replace(tzinfo=UTC),
        checksum=evidence_checksum,
        extractor_version="legacy-platform-seed-v1",
    )
    repository.append_evidence(evidence)
    existing_claims = {
        claim.id: claim
        for claim in repository.list_claims_for_subject(platform_id)
    }
    for scope, values in (("hardware", seed.hardware), ("feature", seed.features)):
        for key, value in sorted(values.items()):
            claim = Claim(
                id=f"claim:legacy:platform:{seed.id}:{scope}:{key}",
                subject_id=platform_id,
                predicate=f"{scope}.{key}",
                value=value,
                state=ClaimState.VERIFIED,
                observed_at=evidence.retrieved_at,
                evidence_ids=[evidence.id],
            )
            existing = existing_claims.get(claim.id)
            if existing is not None and (
                existing.subject_id == claim.subject_id
                and existing.predicate == claim.predicate
                and existing.value == claim.value
                and existing.unit == claim.unit
            ):
                # Verification refreshes state, time, and evidence in place.
                # A migration rerun must preserve that newer operational state.
                continue
            repository.append_claim(claim)
    if metadata_updated:
        repository.record_platform_verification(
            platform_id,
            evidence.retrieved_at,
            evidence_id=evidence.id,
            success=True,
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

    for publisher in SOURCE_PUBLISHERS:
        repository.upsert_publisher(publisher)
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
    # Transitional repair, idempotent per the repository method: drain the
    # volatile-metric conflict backlog on the unconditional rebuild step
    # (the qualification hook turned out to lease only once per DAY, so
    # the amnesty never fired in-window on 2026-08-05).
    amnesty = getattr(repository, "resolve_volatile_conflict_reviews", None)
    amnestied = (
        amnesty(datetime.now(UTC)) if amnesty is not None else 0
    )
    collection_amnesty = getattr(
        repository, "resolve_collection_lineage_reviews", None
    )
    if collection_amnesty is not None:
        amnestied += collection_amnesty(datetime.now(UTC))
    same_origin_amnesty = getattr(
        repository, "resolve_same_origin_conflict_reviews", None
    )
    if same_origin_amnesty is not None:
        amnestied += same_origin_amnesty(datetime.now(UTC))
    purge = getattr(repository, "purge_invalid_lineage_parent_refs", None)
    if purge is not None:
        amnestied += purge(datetime.now(UTC))
    return MigrationReport(
        models_imported=models_imported,
        platforms_imported=platforms_imported,
        history_events_imported=history_imported,
        already_present=already_present,
        warnings=(),
        volatile_reviews_amnestied=amnestied,
    )
