"""Public services exposed by the knowledge feature to downstream features."""

from examtwin.knowledge.corpus_ingestion import render_documents
from examtwin.knowledge.corpus_repository import CorpusRepository
from examtwin.knowledge.difficulty import difficulty_label
from examtwin.knowledge.difficulty_repository import DifficultyRepository
from examtwin.knowledge.document_block_repository import DocumentBlockRepository
from examtwin.knowledge.graph_repository import GraphRepository
from examtwin.knowledge.ingestion import load_vector_index
from examtwin.knowledge.inventory import classify_source, parse_exam_identity
from examtwin.knowledge.knowledge_repository import KnowledgeRepository
from examtwin.knowledge.queries import (
    build_retrieval_cards,
    knowledge_cards_by_code,
    list_knowledge_points,
)
from examtwin.knowledge.retrieval_trace_repository import RetrievalTraceRepository
from examtwin.knowledge.source_context import SourceDocumentReader, source_context
from examtwin.knowledge.vector_retrieval import retrieval_filters

__all__ = [
    "CorpusRepository",
    "DocumentBlockRepository",
    "DifficultyRepository",
    "GraphRepository",
    "KnowledgeRepository",
    "SourceDocumentReader",
    "RetrievalTraceRepository",
    "build_retrieval_cards",
    "classify_source",
    "difficulty_label",
    "list_knowledge_points",
    "knowledge_cards_by_code",
    "load_vector_index",
    "parse_exam_identity",
    "render_documents",
    "source_context",
    "retrieval_filters",
]
