"""Operations endpoints."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from radar.api.dependencies import get_repository, get_services, require_writable
from radar.intelligence.contracts import LineageEdge, ReviewException
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


@router.get("/operations/lineage-suggestions", response_model=list[LineageEdge])
def lineage_suggestions(
    repository: Any = Depends(get_repository),
) -> list[LineageEdge]:
    """Tier-3 inferred parent suggestions awaiting an operator decision."""
    from radar.intelligence.lineage import list_suggestions

    return list_suggestions(repository)


@router.post(
    "/operations/lineage-suggestions/{edge_id:path}/accept",
    response_model=LineageEdge,
    dependencies=[Depends(require_writable)],
)
def accept_lineage_suggestion(
    edge_id: str,
    repository: Any = Depends(get_repository),
) -> LineageEdge:
    from radar.intelligence.lineage import SuggestionError, accept_suggestion

    try:
        return accept_suggestion(repository, edge_id, datetime.now(UTC))
    except SuggestionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/operations/lineage-suggestions/{edge_id:path}/reject",
    status_code=204,
    dependencies=[Depends(require_writable)],
)
def reject_lineage_suggestion(
    edge_id: str,
    repository: Any = Depends(get_repository),
) -> None:
    from radar.intelligence.lineage import SuggestionError, reject_suggestion

    try:
        reject_suggestion(repository, edge_id)
    except SuggestionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
