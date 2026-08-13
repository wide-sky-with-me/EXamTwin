"""Versioned API composition; endpoint implementations live with their capability."""

from fastapi import APIRouter

from examtwin.app.api.corpus import router as corpus_router
from examtwin.app.api.grading import router as grading_router
from examtwin.app.api.graphs import router as graphs_router
from examtwin.app.api.knowledge import router as knowledge_router
from examtwin.app.api.paper_units import router as paper_units_router
from examtwin.app.api.papers import router as papers_router
from examtwin.app.api.system import router as system_router
from examtwin.app.api.workspaces import router as workspaces_router

router = APIRouter()
for capability_router in (
    system_router,
    workspaces_router,
    corpus_router,
    graphs_router,
    knowledge_router,
    paper_units_router,
    papers_router,
    grading_router,
):
    router.include_router(capability_router)
