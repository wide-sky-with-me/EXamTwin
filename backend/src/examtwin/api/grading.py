from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from examtwin.api.dependencies import get_grading_service
from examtwin.api.errors import upstream_http_error
from examtwin.schemas.grading import GradeRequest, GradeResponse, ReviewRequest
from examtwin.services.grading import GradingService

router = APIRouter()


@router.post("/grading/assess", response_model=GradeResponse)
def assess(
    request: GradeRequest,
    service: GradingService = Depends(get_grading_service),
) -> GradeResponse:
    try:
        return service.grade(request)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise upstream_http_error(
            "GRADING_PROVIDER_FAILED",
            "评分服务暂时不可用，请稍后重试",
            error,
        ) from error


@router.get("/grading/reviews")
def reviews(service: GradingService = Depends(get_grading_service)) -> list[dict]:
    return service.pending_reviews()


@router.post("/grading/reviews/{assessment_id}")
def review(
    assessment_id: str,
    request: ReviewRequest,
    service: GradingService = Depends(get_grading_service),
) -> dict:
    try:
        return service.review(assessment_id, request)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
