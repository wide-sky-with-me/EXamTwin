from __future__ import annotations

from examtwin.assessment.assessment_repository import AssessmentRepository
from examtwin.assessment.grading import GradingService
from examtwin.assessment.paper_answering import PaperAnswerService
from examtwin.assessment.paper_job_repository import PaperJobRepository
from examtwin.assessment.paper_job_runtime import PaperJobRuntime
from examtwin.assessment.paper_jobs import PaperJobService
from examtwin.assessment.paper_sources import PaperSourceStore
from examtwin.assessment.paper_unit_repository import PaperUnitRepository
from examtwin.assessment.paper_units import PaperUnitService
from examtwin.assessment.paper_worker import PaperWorker
from examtwin.assessment.rag import RagService
from examtwin.assessment.rubric_repository import RubricRepository
from examtwin.assessment.rubrics import RubricService
from examtwin.assessment.task_events import PostgresPaperJobWakeup
from examtwin.knowledge.corpus_ingestion import CorpusIngestor
from examtwin.knowledge.corpus_repository import CorpusRepository
from examtwin.knowledge.difficulty_repository import DifficultyRepository
from examtwin.knowledge.document_block_repository import DocumentBlockRepository
from examtwin.knowledge.graph_repository import GraphRepository
from examtwin.knowledge.knowledge_build_repository import KnowledgeBuildRepository
from examtwin.knowledge.knowledge_repository import KnowledgeRepository
from examtwin.knowledge.pipeline import KnowledgeBuildPipeline
from examtwin.knowledge.retrieval_trace_repository import RetrievalTraceRepository
from examtwin.knowledge.vector_index_repository import VectorIndexRepository
from examtwin.knowledge.workspace_service import CorpusWorkspaceService
from examtwin.platform.cache_paths import MarkdownCacheStore
from examtwin.platform.config import Settings
from examtwin.platform.database.session import create_session_factory
from examtwin.platform.object_catalog_repository import ObjectCatalogRepository
from examtwin.platform.storage import ManagedObjectStore, build_storage_backend
from examtwin.subjects.dashboard_repository import DashboardRepository
from examtwin.subjects.public import SubjectContext, subject_context
from examtwin.subjects.workspace_repository import WorkspaceRepository


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


def build_corpus_workspace_service(
    settings: Settings,
    subject: SubjectContext | None = None,
) -> CorpusWorkspaceService:
    sessions = create_session_factory(settings.database_url)
    context = subject or subject_context(settings)
    runtime_settings = context.runtime_settings(settings)
    documents = CorpusRepository(sessions)
    object_store = build_object_store(settings)
    return CorpusWorkspaceService(
        settings,
        context,
        workspaces=WorkspaceRepository(sessions),
        documents=documents,
        object_store=object_store,
        ingestor=CorpusIngestor(documents, runtime_settings, context, object_store),
        vector_indexes=VectorIndexRepository(sessions),
        knowledge=KnowledgeRepository(sessions),
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
        markdown_cache=MarkdownCacheStore(build_object_store(settings)),
    )


def build_paper_unit_service(
    settings: Settings,
    subject: SubjectContext | None = None,
) -> PaperUnitService:
    sessions = create_session_factory(settings.database_url)
    context = subject or subject_context(settings)
    return PaperUnitService(
        context,
        PaperUnitRepository(sessions),
        CorpusRepository(sessions),
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
