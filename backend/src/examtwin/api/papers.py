from __future__ import annotations

import asyncio
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

from examtwin.answering_agent.tools.image_generate import AnswerImageStore
from examtwin.api.dependencies import (
    get_answer_image_store,
    get_paper_jobs,
    get_task_events,
)
from examtwin.api.errors import upstream_http_error
from examtwin.schemas.papers import PaperJobCreated, PaperJobResponse
from examtwin.services.paper_jobs import PaperJobService
from examtwin.services.task_events import PostgresTaskEvents, TaskEvent

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
    jobs: PaperJobService = Depends(get_paper_jobs),
) -> PaperJobCreated:
    try:
        return await run_in_threadpool(
            jobs.create_job_from_stream,
            file.filename or "uploaded-paper.md",
            file.file,
            unit_code=unit_code,
        )
    except ValueError as error:
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
