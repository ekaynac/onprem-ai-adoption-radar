"""Deployment-fit endpoints."""

from fastapi import APIRouter, Depends

from radar.api.dependencies import get_services
from radar.intelligence.recommendations import RecommendationView
from radar.intelligence.services.container import IntelligenceServices


router = APIRouter(tags=["deployments"])


@router.get("/deployments/fit", response_model=RecommendationView)
def deployment_fit(
    release_id: str,
    workspace_id: str,
    services: IntelligenceServices = Depends(get_services),
) -> RecommendationView:
    return services.deployments.fit(release_id, workspace_id)
