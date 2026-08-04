"""Composition root for transport-independent application services."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from radar.intelligence.recommendations import (
    LegacyRingRecord,
    RecommendationService,
)
from radar.intelligence.services.catalog import CatalogService
from radar.intelligence.services.deployments import DeploymentService
from radar.intelligence.services.operations import OperationsService
from radar.intelligence.services.releases import ReleaseService


@dataclass(frozen=True)
class IntelligenceServices:
    catalog: CatalogService
    releases: ReleaseService
    deployments: DeploymentService
    operations: OperationsService


def build_services(
    repository: Any,
    *,
    legacy_rings: Mapping[str, LegacyRingRecord] | None = None,
    model_profiles: Mapping[str, Any] | None = None,
) -> IntelligenceServices:
    recommendations = RecommendationService(repository, legacy_rings)
    return IntelligenceServices(
        catalog=CatalogService(repository, recommendations, model_profiles),
        releases=ReleaseService(repository),
        deployments=DeploymentService(recommendations),
        operations=OperationsService(repository),
    )


def build_services_for_root(
    root: Path,
    repository: Any,
) -> IntelligenceServices:
    """Build services with the curated ring bridge loaded from ``root``.

    Every production composition (export, API, MCP) goes through here so
    curated releases carry their authoritative legacy pipeline rings.
    """
    from radar.intelligence.recommendations import legacy_ring_bridge
    from radar.web.public_context import load_public_model_profiles

    profiles = load_public_model_profiles(root)
    return build_services(
        repository,
        legacy_rings=legacy_ring_bridge(profiles),
        model_profiles=profiles,
    )
