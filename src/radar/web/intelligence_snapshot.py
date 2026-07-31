"""Deterministic public intelligence snapshot."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class PublicSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime
    releases: list[dict[str, Any]]
    models: list[dict[str, Any]]
    projects: list[dict[str, Any]]
    model_candidates: list[dict[str, Any]]
    platforms: list[dict[str, Any]]
    hardware: list[dict[str, Any]]
    research: list[dict[str, Any]]
    events: list[dict[str, Any]]
    source_health: dict[str, Any]
    latest_digest: dict[str, str] | None = None


def build_public_snapshot(
    services,
    generated_at: datetime,
    *,
    root: Path | None = None,
) -> PublicSnapshot:
    repository = services.catalog.repository
    canonical_releases = repository.list_all_releases()
    releases = [
        services.releases.get(release.id, now=generated_at)
        for release in canonical_releases
    ]
    models = [
        services.catalog.get(release.id)
        for release in canonical_releases
    ]
    from radar.models_radar.devices import (
        CLUSTER_PRESETS,
        DEVICE_PRESETS,
        NODE_PRESETS,
    )

    hardware = [
        {
            "id": device_id,
            **profile.model_dump(mode="json"),
            "aggregate_memory_gb": profile.total_memory_gb * profile.gpu_count,
        }
        for device_id, profile in sorted(
            {
                **DEVICE_PRESETS,
                **NODE_PRESETS,
                **CLUSTER_PRESETS,
            }.items()
        )
    ]
    research: list[dict[str, Any]] = []
    projects: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    profiles: dict[str, dict[str, Any]] = {}
    legacy_source_health: list[dict[str, Any]] = []
    latest_digest: dict[str, str] | None = None
    if root is not None:
        from radar.web.public_context import (
            load_latest_digest,
            load_public_model_candidates,
            load_public_model_profiles,
            load_public_projects,
            load_public_research_entries,
            load_public_source_health,
        )

        research = [
            item.model_dump(mode="json")
            for item in load_public_research_entries(root)
        ]
        projects = load_public_projects(root)
        profiles = load_public_model_profiles(root)
        candidates = load_public_model_candidates(root, generated_at)
        legacy_source_health = load_public_source_health(root, generated_at)
        latest_digest = load_latest_digest(root)
    operations = services.operations.snapshot()
    release_rows = [item.model_dump(mode="json") for item in releases]
    model_rows = []
    from radar.web.public_context import normalize_public_platforms, profile_claims

    for item in models:
        legacy_id = item.release_id.removeprefix("release:legacy:")
        profile = profiles.get(legacy_id)
        source_url = (
            f"https://huggingface.co/{profile['hf_repo']}"
            if profile and profile.get("hf_repo")
            else None
        )
        model_rows.append(
            {
                "release_id": item.release_id,
                "name": item.name,
                "category": item.category.value,
                "lane": item.lane,
                "lifecycle": item.lifecycle.value,
                "first_observed_at": item.first_observed_at,
                "public_ring": (
                    item.public_recommendation.ring.value
                    if item.public_recommendation.ring
                    else None
                ),
                "reasons": item.public_recommendation.reasons,
                "evidence_ids": item.public_recommendation.evidence_ids,
                "source_url": source_url,
                "source_strength": "trusted_registry",
                "profile": profile,
                "claims": profile_claims(profile, source_url) if profile else [],
            }
        )
    for candidate in candidates:
        release_id = f"release:hf:{candidate['hf_repo'].casefold()}"
        age_hours = max(
            0.0,
            (
                generated_at
                - datetime.fromisoformat(candidate["first_observed_at"])
            ).total_seconds()
            / 3600,
        )
        observation_age_hours = max(
            0.0,
            (
                generated_at
                - datetime.fromisoformat(candidate["last_observed_at"])
            ).total_seconds()
            / 3600,
        )
        citation = {
            "evidence_id": f"evidence:hf:{candidate['hf_repo'].casefold()}",
            "retrieved_at": candidate["last_observed_at"],
            "strength": "trusted_registry",
            "url": candidate["source_url"],
        }
        freshness = "fresh" if observation_age_hours <= 2 else "stale"
        release_rows.append(
            {
                "release_id": release_id,
                "name": candidate["name"],
                "category": candidate["category"],
                "lane": "onprem_adjacent",
                "lifecycle": "detected",
                "first_observed_at": candidate["first_observed_at"],
                "age_hours": age_hours,
                "freshness": freshness,
                "confidence": 0.7,
                "review_status": "clear",
                "citations": [citation],
            }
        )
        profile = {
            "id": release_id,
            "hf_repo": candidate["hf_repo"],
            "family": candidate["family"],
            "modality": candidate["pipeline_tag"],
            "hf_downloads": candidate["downloads"],
            "hf_likes": candidate["likes"],
            "created_at": candidate["created_at"],
            "last_modified": candidate["last_modified"],
        }
        model_rows.append(
            {
                "release_id": release_id,
                "name": candidate["name"],
                "category": candidate["category"],
                "lane": "onprem_adjacent",
                "lifecycle": "detected",
                "first_observed_at": candidate["first_observed_at"],
                "public_ring": None,
                "reasons": [
                    "Detected from Hugging Face; verification and qualification are pending"
                ],
                "evidence_ids": [citation["evidence_id"]],
                "source_url": candidate["source_url"],
                "source_strength": "trusted_registry",
                "profile": profile,
                "claims": [
                    {
                        "predicate": predicate,
                        "state": "candidate",
                        "value": value,
                        "unit": None,
                        "reason": "Trusted-registry observation; verification is pending",
                        "observed_at": candidate["last_observed_at"],
                        "effective_range": None,
                        "citations": [
                            {
                                **citation,
                                "label": "Hugging Face model",
                            }
                        ],
                    }
                    for predicate, value in (
                        ("hf_repo", candidate["hf_repo"]),
                        ("pipeline_tag", candidate["pipeline_tag"]),
                        ("downloads", candidate["downloads"]),
                        ("likes", candidate["likes"]),
                        ("last_modified", candidate["last_modified"]),
                    )
                    if value is not None
                ],
            }
        )
    release_rows.sort(
        key=lambda item: str(item.get("first_observed_at") or ""),
        reverse=True,
    )
    model_rows.sort(
        key=lambda item: str(item.get("first_observed_at") or ""),
        reverse=True,
    )
    operation_payload = operations.model_dump(mode="json")
    canonical_health = operation_payload.get("source_health") or []
    health_by_id = {
        item["source_id"]: item
        for item in [*legacy_source_health, *canonical_health]
    }
    operation_payload["source_health"] = list(health_by_id.values())
    platform_rows = normalize_public_platforms(repository.list_platforms())
    expired_platform_claims = 0
    for platform in platform_rows:
        source_id = f"platform:{str(platform['id']).removeprefix('platform:legacy:')}"
        health = health_by_id.get(source_id)
        if health is not None:
            platform["checked_at"] = health.get("observed_at")
            platform["verification_status"] = health.get("status")
            if health.get("status") != "ok":
                expired_platform_claims += len(platform["hardware"]) + len(
                    platform["features"]
                )
        else:
            platform["verification_status"] = "stale"
            expired_platform_claims += len(platform["hardware"]) + len(
                platform["features"]
            )
    operation_payload["stale_claim_count"] = (
        int(operation_payload.get("stale_claim_count") or 0)
        + expired_platform_claims
    )
    return PublicSnapshot(
        generated_at=generated_at,
        releases=release_rows,
        models=model_rows,
        projects=projects,
        model_candidates=candidates,
        platforms=platform_rows,
        hardware=hardware,
        research=research,
        events=[
            {
                "schema_version": event.schema_version,
                "id": event.id,
                "type": event.type,
                "occurred_at": event.occurred_at,
                "subject_id": event.subject_id,
                "data": event.data,
                "evidence_ids": event.evidence_ids,
            }
            for event in repository.list_events(limit=500, public_only=True)
        ],
        source_health=operation_payload,
        latest_digest=latest_digest,
    )


def write_public_snapshot(snapshot: PublicSnapshot, site_root: Path) -> Path:
    destination = site_root / "data" / "public-snapshot.v1.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            snapshot.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return destination
