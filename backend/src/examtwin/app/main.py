from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from examtwin.app.api.errors import unhandled_api_error
from examtwin.app.api.local_only import LocalOnlyMiddleware
from examtwin.app.api.request_context import RequestContextMiddleware
from examtwin.app.api.request_limits import UploadBodyLimitMiddleware
from examtwin.app.api.router import router
from examtwin.app.composition import build_object_store
from examtwin.assessment.paper_parsing import MAX_UPLOAD_BYTES
from examtwin.contracts.system import API_PREFIX
from examtwin.platform.config import get_settings
from examtwin.platform.database.migrations import upgrade_database
from examtwin.platform.database.session import create_session_factory
from examtwin.platform.observability import configure_logging
from examtwin.subjects.public import subject_package_registry
from examtwin.subjects.workspace_repository import WorkspaceRepository


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging()
    upgrade_database(settings.database_url)
    WorkspaceRepository(
        create_session_factory(settings.database_url)
    ).synchronize_installed_subjects(subject_package_registry(settings.subject_packages_dir).all())
    build_object_store(settings).ping()
    yield


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    UploadBodyLimitMiddleware,
    upload_path=f"{API_PREFIX}/papers/answer",
    # QP uses the paper limit; Booklet uses the corpus upload limit in its handler.
    max_body_bytes=MAX_UPLOAD_BYTES + settings.knowledge_upload_max_bytes + 256 * 1024,
)
app.add_middleware(
    LocalOnlyMiddleware,
    enabled=settings.local_access_only,
    allowed_origins=settings.cors_origin_list,
)
app.add_middleware(RequestContextMiddleware)
app.include_router(router, prefix=API_PREFIX)
app.add_exception_handler(Exception, unhandled_api_error)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "health": f"{API_PREFIX}/health",
    }
