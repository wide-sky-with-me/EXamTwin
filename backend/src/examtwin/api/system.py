from __future__ import annotations

from fastapi import APIRouter, Depends

from examtwin.composition import build_object_store, dashboard_repository
from examtwin.config import Settings, get_settings
from examtwin.schemas.common import HealthResponse, StatsResponse, SubjectPackResponse
from examtwin.services.inventory import corpus_stats
from examtwin.services.subject_context import subject_context

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    subject = subject_context(settings)
    object_store = build_object_store(settings, with_catalog=False)
    object_store.ping()
    return HealthResponse(
        status="ok",
        subject_code=subject.subject_code,
        api_contract_version="2026-08-03.persistence-hardening-v11",  # gitleaks:allow
        capabilities=[
            "paper_jobs_v1",
            "paper_chunk_progress_v1",
            "task_events_v1",
            "answering_agent_v1",
            "answering_tools_v1",
            "answering_mcp_v1",
            "paper_agent_steps_v1",
            "answer_diagrams_v1",
            "required_answer_diagrams_v1",
            "required_answer_artifacts_v1",
            "answer_images_v1",
            "paper_source_pages_v1",
            "paper_question_vision_v1",
            "selective_question_vision_v1",
            "paper_question_concurrency_v1",
            "paper_question_retry_v1",
            "structured_answer_output_v1",
            "question_answer_contract_v1",
            "paired_exam_evidence_v1",
            "adaptive_tool_budget_v1",
            "probability_calculator_v1",
            "source_context_v1",
            "subject_pack_v1",
            "knowledge_build_runs_v1",
            "syllabus_ai_difficulty_v1",
            "vector_index_atomic_publication_v1",
            "versioned_schema_migrations_v1",
            "economics_subject_pack_9640_v1",
            "syllabus_driven_curriculum_v1",
            "curriculum_candidates_v1",
            "managed_object_storage_v1",
            "subject_metadata_v1",
            "bounded_paper_upload_v1",
            "source_identity_diagnostics_v1",
            "local_only_access_v1",
        ],
        llm_model=settings.llm_model,
        embedding_model=settings.embedding_model,
        rerank_model=settings.rerank_model,
        credentials={
            "mineru": settings.mineru_token is not None,
            "llm": settings.llm_provider_api_key is not None,
            "image_generation": (
                settings.image_generation_enabled and settings.image_provider_api_key is not None
            ),
            "siliconflow": settings.siliconflow_api_key is not None,
        },
        object_storage_backend=object_store.backend_name,
    )


@router.get("/subject", response_model=SubjectPackResponse)
def subject_metadata(settings: Settings = Depends(get_settings)) -> SubjectPackResponse:
    pack = subject_context(settings).pack
    return SubjectPackResponse(
        id=pack.id,
        subject_code=pack.subject_code,
        title=pack.title,
        board_name=pack.board.name,
        units=[
            {"code": unit.code, "title": unit.title, "strand": unit.strand}
            for unit in pack.unit_rules
        ],
    )


@router.get("/stats", response_model=StatsResponse)
def stats(settings: Settings = Depends(get_settings)) -> dict:
    return corpus_stats(dashboard_repository(settings))
