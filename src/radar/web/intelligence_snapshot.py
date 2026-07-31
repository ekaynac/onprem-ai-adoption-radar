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
    platforms: list[dict[str, Any]]
    hardware: list[dict[str, Any]]
    research: list[dict[str, Any]]
    events: list[dict[str, Any]]
    source_health: dict[str, Any]


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
        {"id": device_id, **profile.model_dump(mode="json")}
        for device_id, profile in sorted(
            {
                **DEVICE_PRESETS,
                **NODE_PRESETS,
                **CLUSTER_PRESETS,
            }.items()
        )
    ]
    research: list[dict[str, Any]] = []
    if root is not None:
        from radar.mcp_server.technique_queries import load_technique_entries

        research = [
            item.model_dump(mode="json")
            for item in load_technique_entries(root)
        ]
    operations = services.operations.snapshot()
    return PublicSnapshot(
        generated_at=generated_at,
        releases=[
            item.model_dump(mode="json") for item in releases
        ],
        models=[
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
            }
            for item in models
        ],
        platforms=repository.list_platforms(),
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
        source_health=operations.model_dump(mode="json"),
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
