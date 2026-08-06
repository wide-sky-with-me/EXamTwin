from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Query

from examtwin.answering_agent.tools.image_generate import AnswerImageStore
from examtwin.composition import (
    build_grading_service,
    build_object_store,
    build_paper_job_service,
    build_rubric_service,
)
from examtwin.config import Settings, get_settings
from examtwin.services.grading import GradingService
from examtwin.services.paper_jobs import PaperJobService
from examtwin.services.rubrics import RubricService
from examtwin.services.subject_context import SubjectContext, subject_context
from examtwin.services.task_events import PostgresTaskEvents

SUBJECT_HEADER = "X-ExamTwin-Subject"


def get_subject_context(
    settings: Settings = Depends(get_settings),
    x_examtwin_subject: str | None = Header(default=None, alias=SUBJECT_HEADER),
    subject: str | None = Query(default=None),
) -> SubjectContext:
    selector = (x_examtwin_subject or subject or "").strip()
    if not selector:
        raise HTTPException(
            status_code=400,
            detail="请先选择科目，再访问该科目的资料、知识、答题或评分功能",
        )
    try:
        return subject_context(settings, selector)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


def get_paper_jobs(
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> PaperJobService:
    return build_paper_job_service(settings, subject)


def get_grading_service(
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> GradingService:
    return build_grading_service(settings, subject)


def get_rubric_service(
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> RubricService:
    return build_rubric_service(settings, subject)


def get_task_events(settings: Settings = Depends(get_settings)) -> PostgresTaskEvents:
    return PostgresTaskEvents(settings.database_url)


def get_answer_image_store(
    settings: Settings = Depends(get_settings),
) -> AnswerImageStore:
    return AnswerImageStore(
        build_object_store(settings),
        retention_days=settings.answer_artifact_retention_days,
    )
