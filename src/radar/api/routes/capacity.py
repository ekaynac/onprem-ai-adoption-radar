"""Capacity planning endpoints over the deterministic solver."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from radar.api.dependencies import get_root


router = APIRouter(tags=["capacity"])


@lru_cache(maxsize=4)
def _service(root: str) -> Any:
    from radar.mcp_server.capacity_queries import CapacityQueryService

    return CapacityQueryService(Path(root))


class CapacityPlanRequest(BaseModel):
    model_id: str
    device: str
    concurrent_requests: int = Field(ge=1, le=100_000)
    avg_context_tokens: int = Field(ge=1, le=10_000_000)
    target_tps_per_user: float | None = Field(default=None, gt=0)
    quant: str | None = None
    kv_dtype: str = "fp16"
    engine: str = "vllm"


class CapacityFitRequest(BaseModel):
    model_id: str
    device: str
    context_tokens: int = Field(default=4096, ge=1, le=10_000_000)


@router.get("/capacity/devices")
def capacity_devices(root: Path = Depends(get_root)) -> list[dict[str, Any]]:
    from radar.mcp_server.model_queries import ModelQueryService

    return ModelQueryService(root).list_devices()


@router.post("/capacity/plan")
def capacity_plan(
    request: CapacityPlanRequest,
    root: Path = Depends(get_root),
) -> dict[str, Any]:
    plan = _service(str(root)).plan_capacity(
        request.model_id,
        request.device,
        request.concurrent_requests,
        request.avg_context_tokens,
        request.target_tps_per_user,
        request.quant,
        request.kv_dtype,
        request.engine,
    )
    if plan is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown model: {request.model_id}",
        )
    return plan


@router.post("/capacity/fit")
def capacity_fit(
    request: CapacityFitRequest,
    root: Path = Depends(get_root),
) -> dict[str, Any]:
    from radar.mcp_server.model_queries import ModelQueryService
    from radar.models_radar.devices import DeviceError

    try:
        verdict = ModelQueryService(root).can_run(
            request.model_id,
            request.device,
            request.context_tokens,
        )
    except DeviceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if verdict is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown model: {request.model_id}",
        )
    return verdict
