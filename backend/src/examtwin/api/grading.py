from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from examtwin.api.dependencies import get_grading_service, get_rubric_service
from examtwin.api.errors import upstream_http_error
from examtwin.schemas.grading import (
    GradeResponse,
    ReviewDecisionResponse,
    ReviewQueueItem,
    ReviewRequest,
)
from examtwin.schemas.rubrics import (
    ConfirmRubricRequest,
    CreateRubricRequest,
    GradePaperQuestionRequest,
    GradingPaperSummary,
    PaperAssessmentResponse,
    ReviewRubricCriterionRequest,
    RubricSetResponse,
    RubricSetSummary,
)
from examtwin.services.grading import GradingService
from examtwin.services.rubrics import RubricService

router = APIRouter()


@router.post("/grading/rubrics", response_model=RubricSetResponse)
def create_rubric(
    request: CreateRubricRequest,
    service: RubricService = Depends(get_rubric_service),
) -> RubricSetResponse:
    try:
        return RubricSetResponse.model_validate(
            service.create(
                paper_job_id=request.paper_job_id,
                source_document_id=request.source_document_id,
            )
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise upstream_http_error(
            "RUBRIC_EXTRACTION_FAILED",
            "评分方案解析失败，请检查文档转换状态后重试",
            error,
        ) from error


@router.get("/grading/papers", response_model=list[GradingPaperSummary])
def grading_papers(
    service: RubricService = Depends(get_rubric_service),
) -> list[GradingPaperSummary]:
    return [GradingPaperSummary.model_validate(item) for item in service.papers_ready_for_grading()]


@router.get("/grading/rubrics", response_model=list[RubricSetSummary])
def list_rubrics(
    paper_job_id: str,
    service: RubricService = Depends(get_rubric_service),
) -> list[RubricSetSummary]:
    return [RubricSetSummary.model_validate(item) for item in service.list_for_paper(paper_job_id)]


@router.get("/grading/rubrics/{rubric_id}", response_model=RubricSetResponse)
def rubric_detail(
    rubric_id: str,
    service: RubricService = Depends(get_rubric_service),
) -> RubricSetResponse:
    try:
        return RubricSetResponse.model_validate(service.get(rubric_id))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post(
    "/grading/rubrics/{rubric_id}/criteria/{criterion_id}/review",
    response_model=RubricSetResponse,
)
def review_rubric_criterion(
    rubric_id: str,
    criterion_id: str,
    request: ReviewRubricCriterionRequest,
    service: RubricService = Depends(get_rubric_service),
) -> RubricSetResponse:
    try:
        updates = (
            request.updates.model_dump(exclude_unset=True) if request.updates is not None else {}
        )
        return RubricSetResponse.model_validate(
            service.review_criterion(
                rubric_id,
                criterion_id,
                review_status=request.review_status,
                reviewer=request.reviewer,
                note=request.note,
                updates=updates,
            )
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/grading/rubrics/{rubric_id}/confirm", response_model=RubricSetResponse)
def confirm_rubric(
    rubric_id: str,
    request: ConfirmRubricRequest,
    service: RubricService = Depends(get_rubric_service),
) -> RubricSetResponse:
    try:
        return RubricSetResponse.model_validate(
            service.confirm(rubric_id, reviewer=request.reviewer)
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/grading/papers/{paper_job_id}/questions/{position}/assess",
    response_model=GradeResponse,
)
def assess_paper_question(
    paper_job_id: str,
    position: int,
    request: GradePaperQuestionRequest,
    service: RubricService = Depends(get_rubric_service),
) -> GradeResponse:
    try:
        return service.grade_question(
            paper_job_id,
            position,
            rubric_set_id=request.rubric_set_id,
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise upstream_http_error(
            "GRADING_PROVIDER_FAILED",
            "评分服务暂时不可用，请稍后重试",
            error,
        ) from error


@router.get(
    "/grading/papers/{paper_job_id}/assessments",
    response_model=list[PaperAssessmentResponse],
)
def paper_assessments(
    paper_job_id: str,
    service: RubricService = Depends(get_rubric_service),
) -> list[PaperAssessmentResponse]:
    try:
        return [
            PaperAssessmentResponse.model_validate(item)
            for item in service.assessments_for_paper(paper_job_id)
        ]
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/grading/reviews", response_model=list[ReviewQueueItem])
def reviews(service: GradingService = Depends(get_grading_service)) -> list[ReviewQueueItem]:
    return [ReviewQueueItem.model_validate(item) for item in service.pending_reviews()]


@router.post("/grading/reviews/{assessment_id}", response_model=ReviewDecisionResponse)
def review(
    assessment_id: str,
    request: ReviewRequest,
    service: GradingService = Depends(get_grading_service),
) -> ReviewDecisionResponse:
    try:
        return ReviewDecisionResponse.model_validate(service.review(assessment_id, request))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
