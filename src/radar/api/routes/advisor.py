"""The Answer Machine endpoint: task + hardware + policy → cited shortlist."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from radar.api.dependencies import get_root


router = APIRouter(tags=["advisor"])


class RecommendRequest(BaseModel):
    task: str
    device: str
    allowed_licenses: list[str] | None = None
    min_context: int | None = Field(default=None, ge=1)
    limit: int = Field(default=5, ge=1, le=10)
    include_unverified: bool = False


@router.post("/recommend")
def recommend(
    request: RecommendRequest,
    root: Path = Depends(get_root),
) -> dict[str, Any]:
    from radar.models_radar.advisor import build_answers
    from radar.models_radar.devices import DeviceError
    from radar.web.public_context import load_public_model_profiles

    try:
        return build_answers(
            load_public_model_profiles(root),
            request.device,
            request.task,
            allowed_licenses=request.allowed_licenses,
            min_context=request.min_context,
            limit=request.limit,
            include_unverified=request.include_unverified,
        )
    except (ValueError, DeviceError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
