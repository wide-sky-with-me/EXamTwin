from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from examtwin.app.api.dependencies import (
    get_answer_image_store,
    get_paper_jobs,
    get_subject_context,
    get_task_events,
)
from examtwin.app.api.errors import upstream_http_error
from examtwin.app.composition import build_paper_job_service
from examtwin.assessment.answering_agent.tools.image_generate import AnswerImageStore
from examtwin.assessment.paper_jobs import PaperJobService
from examtwin.assessment.task_events import PostgresTaskEvents, TaskEvent
from examtwin.contracts.papers import PaperJobCreated, PaperJobResponse
from examtwin.platform.config import Settings, get_settings
from examtwin.platform.database.session import create_session_factory
from examtwin.subjects.public import SubjectContext
from examtwin.subjects.workspace_repository import WorkspaceRepository

router = APIRouter()


async def _wait_for_task_event_or_disconnect(
    websocket: WebSocket,
    updates: AsyncIterator[TaskEvent],
) -> bool:
    event_task = asyncio.ensure_future(anext(updates))
    disconnect_task = asyncio.create_task(websocket.receive())
    done, pending = await asyncio.wait(
        {event_task, disconnect_task}, return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
    for task in pending:
        with suppress(asyncio.CancelledError):
            await task
    if disconnect_task in done:
        return False
    event_task.result()
    return True


@router.post(
    "/papers/answer",
    response_model=PaperJobCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def answer_paper(
    file: UploadFile = File(...),
    unit_code: str | None = Form(default=None),
    knowledge_base_version_ids: str | None = Form(default=None),
    include_supplementary: bool = Form(default=False),
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> PaperJobCreated:
    try:
        subject.require_paper_capability()
        requested: list[str] = []
        if knowledge_base_version_ids:
            parsed = json.loads(knowledge_base_version_ids)
            if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
                raise ValueError("knowledge_base_version_ids 必须是字符串数组")
            requested = parsed
        repository = WorkspaceRepository(create_session_factory(settings.database_url))
        snapshot = (
            repository.retrieval_snapshot_for_versions(subject.id, requested)
            if requested
            else repository.active_retrieval_snapshot(
                subject.id,
                include_supplementary=include_supplementary,
            )
        )
        collections = tuple(str(item) for item in snapshot["collections"])
        if not collections:
            raise ValueError("整卷作答前必须先构建并发布知识库版本")
        selected_subject = subject.with_retrieval_snapshot(
            version_ids=tuple(str(item) for item in snapshot["version_ids"]),
            collections=collections,
            graph_version_id=snapshot.get("graph_version_id"),
        )
        jobs = build_paper_job_service(settings, selected_subject)
        return await run_in_threadpool(
            jobs.create_job_from_stream,
            file.filename or "uploaded-paper.md",
            file.file,
            unit_code=unit_code,
        )
    except (LookupError, ValueError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise upstream_http_error(
            "PAPER_JOB_CREATION_FAILED",
            "试卷任务创建失败，请稍后重试",
            error,
        ) from error


@router.get("/papers/jobs/{job_id}", response_model=PaperJobResponse)
def paper_job(
    job_id: str,
    jobs: PaperJobService = Depends(get_paper_jobs),
) -> PaperJobResponse:
    try:
        return jobs.get_job(job_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.websocket("/papers/jobs/{job_id}/events")
async def paper_job_events(
    websocket: WebSocket,
    job_id: str,
    jobs: PaperJobService = Depends(get_paper_jobs),
    events: PostgresTaskEvents = Depends(get_task_events),
) -> None:
    try:
        await asyncio.to_thread(jobs.get_job, job_id)
    except LookupError as error:
        await websocket.close(code=4404, reason=str(error))
        return
    try:
        async with events.subscribe("paper_job", job_id) as updates:
            await websocket.accept()
            while True:
                snapshot = await asyncio.to_thread(jobs.get_job, job_id)
                await websocket.send_json(
                    {
                        "type": "snapshot",
                        "topic": "paper_job",
                        "resource_id": job_id,
                        "data": snapshot.model_dump(mode="json"),
                    }
                )
                if snapshot.status in {"completed", "partial_failed", "failed"}:
                    return
                if not await _wait_for_task_event_or_disconnect(websocket, updates):
                    return
    except (LookupError, StopAsyncIteration, WebSocketDisconnect):
        return


@router.get("/papers/jobs/{job_id}/source", response_class=FileResponse)
def paper_job_source(
    job_id: str,
    jobs: PaperJobService = Depends(get_paper_jobs),
) -> FileResponse:
    try:
        path, _filename, suffix = jobs.source_file(job_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    media_type = "application/pdf" if suffix == ".pdf" else "text/markdown; charset=utf-8"
    return FileResponse(path, media_type=media_type)


@router.get("/answer-assets/{asset_id}.png", response_class=FileResponse)
def answer_image_asset(
    asset_id: str,
    store: AnswerImageStore = Depends(get_answer_image_store),
) -> FileResponse:
    try:
        path = store.resolve(asset_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(
        path,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.get("/papers/jobs/{job_id}/source/pages/{page_number}", response_class=FileResponse)
def paper_job_source_page(
    job_id: str,
    page_number: int,
    jobs: PaperJobService = Depends(get_paper_jobs),
) -> FileResponse:
    try:
        path = jobs.source_page(job_id, page_number)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return FileResponse(path, media_type="image/jpeg")


@router.post(
    "/papers/jobs/{job_id}/retry",
    response_model=PaperJobCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_paper_job(
    job_id: str,
    jobs: PaperJobService = Depends(get_paper_jobs),
) -> PaperJobCreated:
    try:
        return jobs.retry(job_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post(
    "/papers/jobs/{job_id}/questions/{position}/retry",
    response_model=PaperJobCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_paper_question(
    job_id: str,
    position: int,
    jobs: PaperJobService = Depends(get_paper_jobs),
) -> PaperJobCreated:
    try:
        return jobs.retry_question(job_id, position)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
