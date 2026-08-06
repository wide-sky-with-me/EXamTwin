from __future__ import annotations

from examtwin.config import Settings
from examtwin.persistence.assessment_repository import AssessmentRepository
from examtwin.persistence.corpus_repository import CorpusRepository
from examtwin.persistence.dashboard_repository import DashboardRepository
from examtwin.persistence.difficulty_repository import DifficultyRepository
from examtwin.persistence.document_block_repository import DocumentBlockRepository
from examtwin.persistence.graph_repository import GraphRepository
from examtwin.persistence.knowledge_build_repository import KnowledgeBuildRepository
from examtwin.persistence.knowledge_repository import KnowledgeRepository
from examtwin.persistence.object_catalog_repository import ObjectCatalogRepository
from examtwin.persistence.paper_job_repository import PaperJobRepository
from examtwin.persistence.retrieval_trace_repository import RetrievalTraceRepository
from examtwin.persistence.rubric_repository import RubricRepository
from examtwin.persistence.session import create_session_factory
from examtwin.persistence.vector_index_repository import VectorIndexRepository
from examtwin.persistence.workspace_repository import WorkspaceRepository
from examtwin.services.corpus_ingestion import CorpusIngestor
from examtwin.services.grading import GradingService
from examtwin.services.knowledge_pipeline import KnowledgeBuildPipeline
from examtwin.services.paper_answering import PaperAnswerService
from examtwin.services.paper_job_runtime import PaperJobRuntime
from examtwin.services.paper_jobs import PaperJobService
from examtwin.services.paper_sources import PaperSourceStore
from examtwin.services.paper_worker import PaperWorker
from examtwin.services.rag import RagService
from examtwin.services.rubrics import RubricService
from examtwin.services.subject_context import SubjectContext, subject_context
from examtwin.services.task_events import PostgresPaperJobWakeup
from examtwin.storage import ManagedObjectStore, build_storage_backend


def build_object_store(
    settings: Settings,
    *,
    with_catalog: bool = True,
) -> ManagedObjectStore:
    backend = build_storage_backend(settings)
    catalog = (
        ObjectCatalogRepository(create_session_factory(settings.database_url))
        if with_catalog
        else None
    )
    return ManagedObjectStore(backend, catalog)


def corpus_repository(settings: Settings) -> CorpusRepository:
    return CorpusRepository(create_session_factory(settings.database_url))


def dashboard_repository(settings: Settings) -> DashboardRepository:
    return DashboardRepository(create_session_factory(settings.database_url))


def difficulty_repository(settings: Settings) -> DifficultyRepository:
    return DifficultyRepository(create_session_factory(settings.database_url))


def knowledge_repository(settings: Settings) -> KnowledgeRepository:
    return KnowledgeRepository(create_session_factory(settings.database_url))


def vector_index_repository(settings: Settings) -> VectorIndexRepository:
    return VectorIndexRepository(create_session_factory(settings.database_url))


def retrieval_trace_repository(settings: Settings) -> RetrievalTraceRepository:
    return RetrievalTraceRepository(
        create_session_factory(settings.database_url),
        max_rows_per_subject=settings.retrieval_trace_max_rows_per_subject,
    )


def build_corpus_ingestor(
    settings: Settings,
    subject: SubjectContext | None = None,
) -> CorpusIngestor:
    context = subject or subject_context(settings)
    runtime_settings = context.runtime_settings(settings)
    return CorpusIngestor(
        corpus_repository(settings),
        runtime_settings,
        context,
        build_object_store(settings),
    )


def build_knowledge_pipeline(
    settings: Settings,
    subject: SubjectContext | None = None,
) -> KnowledgeBuildPipeline:
    sessions = create_session_factory(settings.database_url)
    context = subject or subject_context(settings)
    return KnowledgeBuildPipeline(
        context.runtime_settings(settings),
        context,
        KnowledgeBuildRepository(sessions),
        KnowledgeRepository(sessions),
        WorkspaceRepository(sessions),
        DocumentBlockRepository(sessions),
    )


def build_rag_service(
    settings: Settings,
    subject: SubjectContext | None = None,
) -> RagService:
    sessions = create_session_factory(settings.database_url)
    context = subject or subject_context(settings)
    runtime_settings = context.runtime_settings(settings)
    return RagService(
        runtime_settings,
        context,
        KnowledgeRepository(sessions),
        CorpusRepository(sessions),
        RetrievalTraceRepository(
            sessions,
            max_rows_per_subject=runtime_settings.retrieval_trace_max_rows_per_subject,
        ),
        DocumentBlockRepository(sessions),
        GraphRepository(sessions),
        object_store=build_object_store(settings),
    )


def build_grading_service(
    settings: Settings,
    subject: SubjectContext | None = None,
) -> GradingService:
    sessions = create_session_factory(settings.database_url)
    context = subject or subject_context(settings)
    return GradingService(
        CorpusRepository(sessions),
        AssessmentRepository(sessions),
        context.runtime_settings(settings),
        context,
    )


def build_rubric_service(
    settings: Settings,
    subject: SubjectContext | None = None,
) -> RubricService:
    sessions = create_session_factory(settings.database_url)
    context = subject or subject_context(settings)
    runtime_settings = context.runtime_settings(settings)
    documents = CorpusRepository(sessions)
    assessments = AssessmentRepository(sessions)
    grading = GradingService(documents, assessments, runtime_settings, context)
    return RubricService(
        runtime_settings,
        context,
        documents,
        PaperJobRepository(sessions, lease_seconds=settings.paper_lease_seconds),
        RubricRepository(sessions),
        assessments,
        grading,
    )


def build_paper_job_service(
    settings: Settings,
    subject: SubjectContext | None = None,
) -> PaperJobService:
    context = subject or subject_context(settings)
    return PaperJobService(
        context.runtime_settings(settings),
        context,
        repository=PaperJobRepository(
            create_session_factory(settings.database_url),
            lease_seconds=settings.paper_lease_seconds,
        ),
        files=PaperSourceStore(
            build_object_store(settings),
            retention_days=settings.paper_object_retention_days,
        ),
    )


def build_paper_worker(settings: Settings) -> PaperWorker:
    sessions = create_session_factory(settings.database_url)
    subject = subject_context(settings)
    documents = CorpusRepository(sessions)
    knowledge = KnowledgeRepository(sessions)
    retrieval_traces = RetrievalTraceRepository(
        sessions,
        max_rows_per_subject=settings.retrieval_trace_max_rows_per_subject,
    )
    object_store = build_object_store(settings)

    def answer_service_for(context: SubjectContext) -> PaperAnswerService:
        runtime_settings = context.runtime_settings(settings)
        rag = RagService(
            runtime_settings,
            context,
            knowledge,
            documents,
            retrieval_traces,
            DocumentBlockRepository(sessions),
            GraphRepository(sessions),
            object_store=object_store,
        )
        return PaperAnswerService(
            runtime_settings,
            context,
            knowledge_repository=knowledge,
            rag=rag,
        )

    answers = answer_service_for(subject)
    jobs = PaperJobRuntime(
        PaperJobRepository(
            sessions,
            lease_seconds=settings.paper_lease_seconds,
        ),
        PaperSourceStore(
            build_object_store(settings),
            retention_days=settings.paper_object_retention_days,
        ),
    )
    return PaperWorker(
        settings,
        subject,
        jobs=jobs,
        answer_service=answers,
        wakeup=PostgresPaperJobWakeup(settings.database_url),
        subject_resolver=lambda selector: subject_context(settings, selector),
        answer_service_factory=answer_service_for,
    )
