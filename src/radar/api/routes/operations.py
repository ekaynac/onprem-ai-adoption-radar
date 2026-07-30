"""Operations endpoints."""

from fastapi import APIRouter, Depends

from radar.api.dependencies import get_services
from radar.intelligence.services.container import IntelligenceServices
from radar.intelligence.services.operations import OperationsSnapshot


router = APIRouter(tags=["operations"])


@router.get("/operations", response_model=OperationsSnapshot)
def operations_snapshot(
    services: IntelligenceServices = Depends(get_services),
) -> OperationsSnapshot:
    return services.operations.snapshot()
