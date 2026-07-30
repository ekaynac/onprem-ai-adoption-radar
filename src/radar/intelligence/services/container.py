"""Composition root for transport-independent application services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from radar.intelligence.recommendations import RecommendationService
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


def build_services(repository: Any) -> IntelligenceServices:
    recommendations = RecommendationService(repository)
    return IntelligenceServices(
        catalog=CatalogService(repository, recommendations),
        releases=ReleaseService(repository),
        deployments=DeploymentService(recommendations),
        operations=OperationsService(repository),
    )
