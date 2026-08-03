"""Versioned API composition; endpoint implementations live with their capability."""

from fastapi import APIRouter

from examtwin.api.corpus import router as corpus_router
from examtwin.api.grading import router as grading_router
from examtwin.api.knowledge import router as knowledge_router
from examtwin.api.papers import router as papers_router
from examtwin.api.system import router as system_router

router = APIRouter()
for capability_router in (
    system_router,
    corpus_router,
    knowledge_router,
    papers_router,
    grading_router,
):
    router.include_router(capability_router)
