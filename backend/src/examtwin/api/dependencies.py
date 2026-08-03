from __future__ import annotations

from fastapi import Depends

from examtwin.answering_agent.tools.image_generate import AnswerImageStore
from examtwin.composition import build_grading_service, build_object_store, build_paper_job_service
from examtwin.config import Settings, get_settings
from examtwin.services.grading import GradingService
from examtwin.services.paper_jobs import PaperJobService
from examtwin.services.task_events import PostgresTaskEvents


def get_paper_jobs(settings: Settings = Depends(get_settings)) -> PaperJobService:
    return build_paper_job_service(settings)


def get_grading_service(settings: Settings = Depends(get_settings)) -> GradingService:
    return build_grading_service(settings)


def get_task_events(settings: Settings = Depends(get_settings)) -> PostgresTaskEvents:
    return PostgresTaskEvents(settings.database_url)


def get_answer_image_store(
    settings: Settings = Depends(get_settings),
) -> AnswerImageStore:
    return AnswerImageStore(
        build_object_store(settings),
        retention_days=settings.answer_artifact_retention_days,
    )
