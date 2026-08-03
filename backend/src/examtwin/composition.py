from __future__ import annotations

from examtwin.config import Settings
from examtwin.persistence.assessment_repository import AssessmentRepository
from examtwin.persistence.corpus_repository import CorpusRepository
from examtwin.persistence.dashboard_repository import DashboardRepository
from examtwin.persistence.difficulty_repository import DifficultyRepository
from examtwin.persistence.knowledge_build_repository import KnowledgeBuildRepository
from examtwin.persistence.knowledge_repository import KnowledgeRepository
from examtwin.persistence.object_catalog_repository import ObjectCatalogRepository
from examtwin.persistence.paper_job_repository import PaperJobRepository
from examtwin.persistence.session import create_session_factory
from examtwin.persistence.vector_index_repository import VectorIndexRepository
from examtwin.services.corpus_ingestion import CorpusIngestor
from examtwin.services.grading import GradingService
from examtwin.services.knowledge_pipeline import KnowledgeBuildPipeline
from examtwin.services.paper_answering import PaperAnswerService
from examtwin.services.paper_job_runtime import PaperJobRuntime
from examtwin.services.paper_jobs import PaperJobService
from examtwin.services.paper_sources import PaperSourceStore
from examtwin.services.paper_worker import PaperWorker
from examtwin.services.rag import RagService
from examtwin.services.subject_context import subject_context
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


def build_corpus_ingestor(settings: Settings) -> CorpusIngestor:
    return CorpusIngestor(
        corpus_repository(settings),
        settings,
        subject_context(settings),
        build_object_store(settings),
    )


def build_knowledge_pipeline(settings: Settings) -> KnowledgeBuildPipeline:
    sessions = create_session_factory(settings.database_url)
    return KnowledgeBuildPipeline(
        settings,
        subject_context(settings),
        KnowledgeBuildRepository(sessions),
        KnowledgeRepository(sessions),
    )


def build_rag_service(settings: Settings) -> RagService:
    sessions = create_session_factory(settings.database_url)
    return RagService(
        settings,
        subject_context(settings),
        KnowledgeRepository(sessions),
        CorpusRepository(sessions),
        object_store=build_object_store(settings),
    )


def build_grading_service(settings: Settings) -> GradingService:
    sessions = create_session_factory(settings.database_url)
    return GradingService(
        CorpusRepository(sessions),
        AssessmentRepository(sessions),
        settings,
    )


def build_paper_job_service(settings: Settings) -> PaperJobService:
    return PaperJobService(
        settings,
        subject_context(settings),
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
    object_store = build_object_store(settings)
    rag = RagService(settings, subject, knowledge, documents, object_store=object_store)
    answers = PaperAnswerService(
        settings,
        subject,
        knowledge_repository=knowledge,
        rag=rag,
    )
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
    )
