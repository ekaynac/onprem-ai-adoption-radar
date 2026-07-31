"""Operations endpoints."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from radar.api.dependencies import get_repository, get_services, require_writable
from radar.intelligence.contracts import ReviewException
from radar.intelligence.review import InvalidReviewResolution, ReviewService
from radar.intelligence.services.container import IntelligenceServices
from radar.intelligence.services.operations import OperationsSnapshot


router = APIRouter(tags=["operations"])


@router.get("/operations", response_model=OperationsSnapshot)
def operations_snapshot(
    services: IntelligenceServices = Depends(get_services),
) -> OperationsSnapshot:
    return services.operations.snapshot()


class ReviewResolutionInput(BaseModel):
    resolution: str
    evidence_ids: list[str] = Field(default_factory=list)


@router.get("/operations/reviews", response_model=list[ReviewException])
def review_queue(
    open_only: bool = True,
    repository: Any = Depends(get_repository),
) -> list[ReviewException]:
    return repository.list_review_exceptions(open_only=open_only)


@router.post(
    "/operations/reviews/{exception_id}/resolve",
    response_model=ReviewException,
    dependencies=[Depends(require_writable)],
)
def resolve_review(
    exception_id: str,
    value: ReviewResolutionInput,
    repository: Any = Depends(get_repository),
) -> ReviewException:
    try:
        ReviewService(repository).resolve(
            exception_id,
            value.resolution,
            evidence_ids=value.evidence_ids,
            now=datetime.now(UTC),
        )
    except InvalidReviewResolution as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return repository.get_review_exception(exception_id)
