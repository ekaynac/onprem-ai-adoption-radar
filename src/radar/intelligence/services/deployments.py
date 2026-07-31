"""Deployment-facing application projections."""

from __future__ import annotations

from radar.intelligence.recommendations import (
    RecommendationService,
    RecommendationView,
)


class DeploymentService:
    def __init__(self, recommendations: RecommendationService):
        self.recommendations = recommendations

    def fit(
        self,
        release_id: str,
        workspace_id: str,
    ) -> RecommendationView:
        return self.recommendations.for_workspace(
            release_id,
            workspace_id,
        )
