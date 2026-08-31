from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query

from examtwin.app.api.dependencies import (
    get_difficulty_evidence_service,
    get_reviewer_identity,
    get_subject_context,
)
from examtwin.assessment.difficulty_evidence import DifficultyEvidenceService
from examtwin.contracts.difficulty_evidence import (
    DifficultyPublishRequest,
    DifficultyReviewRequest,
    DifficultyRunCreateRequest,
    DifficultyRunDetail,
    DifficultyRunSummary,
)
from examtwin.subjects.public import SubjectContext

router = APIRouter(
    prefix="/subject-workspaces/{workspace_id}/difficulty-evidence",
    tags=["difficulty-evidence"],
)


def _require_workspace(workspace_id: str, subject: SubjectContext) -> None:
    if workspace_id != subject.id:
        raise HTTPException(status_code=404, detail="科目工作区不存在")


def _raise_api_error(error: Exception) -> NoReturn:
    if isinstance(error, LookupError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    message = str(error)
    conflict_terms = (
        "stale",
        "immutable",
        "reviewed",
        "published",
        "archived",
        "changed after extraction",
    )
    status_code = 409 if any(term in message for term in conflict_terms) else 422
    raise HTTPException(status_code=status_code, detail=message) from error


@router.get("/runs", response_model=list[DifficultyRunSummary])
def list_difficulty_runs(
    workspace_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    subject: SubjectContext = Depends(get_subject_context),
    service: DifficultyEvidenceService = Depends(get_difficulty_evidence_service),
) -> list[dict[str, Any]]:
    _require_workspace(workspace_id, subject)
    return service.list_runs(subject.id, limit=limit)


@router.post("/runs", response_model=DifficultyRunDetail)
def create_difficulty_run(
    workspace_id: str,
    request: DifficultyRunCreateRequest,
    subject: SubjectContext = Depends(get_subject_context),
    service: DifficultyEvidenceService = Depends(get_difficulty_evidence_service),
) -> dict[str, Any]:
    _require_workspace(workspace_id, subject)
    try:
        return service.create_from_source(
            subject=subject,
            source_document_id=request.source_document_id,
        )
    except (LookupError, RuntimeError, ValueError) as error:
        _raise_api_error(error)


@router.get("/runs/{run_id}", response_model=DifficultyRunDetail)
def get_difficulty_run(
    workspace_id: str,
    run_id: str,
    subject: SubjectContext = Depends(get_subject_context),
    service: DifficultyEvidenceService = Depends(get_difficulty_evidence_service),
) -> dict[str, Any]:
    _require_workspace(workspace_id, subject)
    try:
        return service.require_run(subject.id, run_id)
    except (LookupError, ValueError) as error:
        _raise_api_error(error)


@router.post(
    "/runs/{run_id}/candidates/{candidate_id}/reviews",
    response_model=DifficultyRunDetail,
)
def review_difficulty_candidate(
    workspace_id: str,
    run_id: str,
    candidate_id: str,
    request: DifficultyReviewRequest,
    reviewer: str = Depends(get_reviewer_identity),
    subject: SubjectContext = Depends(get_subject_context),
    service: DifficultyEvidenceService = Depends(get_difficulty_evidence_service),
) -> dict[str, Any]:
    _require_workspace(workspace_id, subject)
    try:
        return service.review_candidate(
            subject_id=subject.id,
            run_id=run_id,
            candidate_id=candidate_id,
            review=request,
            reviewer=reviewer,
        )
    except (LookupError, ValueError) as error:
        _raise_api_error(error)


@router.post("/runs/{run_id}/publish", response_model=DifficultyRunDetail)
def publish_difficulty_run(
    workspace_id: str,
    run_id: str,
    request: DifficultyPublishRequest,
    reviewer: str = Depends(get_reviewer_identity),
    subject: SubjectContext = Depends(get_subject_context),
    service: DifficultyEvidenceService = Depends(get_difficulty_evidence_service),
) -> dict[str, Any]:
    _require_workspace(workspace_id, subject)
    try:
        service.publish_run(
            subject_id=subject.id,
            run_id=run_id,
            expected_fingerprint=request.expected_run_fingerprint,
            reviewer=reviewer,
        )
        return service.require_run(subject.id, run_id)
    except (LookupError, ValueError) as error:
        _raise_api_error(error)
