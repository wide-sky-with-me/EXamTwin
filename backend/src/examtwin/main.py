from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from examtwin.api.errors import unhandled_api_error
from examtwin.api.local_only import LocalOnlyMiddleware
from examtwin.api.request_context import RequestContextMiddleware
from examtwin.api.request_limits import UploadBodyLimitMiddleware
from examtwin.api.router import router
from examtwin.composition import build_object_store
from examtwin.config import get_settings
from examtwin.observability import configure_logging
from examtwin.persistence.migrations import upgrade_database
from examtwin.services.paper_parsing import MAX_UPLOAD_BYTES


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging()
    upgrade_database(settings.database_url)
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
    upload_path=f"{settings.api_prefix}/papers/answer",
    # Multipart boundaries and form fields add a small amount beyond the file itself.
    max_body_bytes=MAX_UPLOAD_BYTES + 256 * 1024,
)
app.add_middleware(LocalOnlyMiddleware, enabled=settings.local_access_only)
app.add_middleware(RequestContextMiddleware)
app.include_router(router, prefix=settings.api_prefix)
app.add_exception_handler(Exception, unhandled_api_error)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "health": f"{settings.api_prefix}/health",
    }
