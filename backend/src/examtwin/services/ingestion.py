from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from examtwin.config import Settings
from examtwin.persistence.knowledge_repository import KnowledgeRepository
from examtwin.persistence.session import utcnow
from examtwin.persistence.vector_index_repository import VectorIndexRepository
from examtwin.schemas.common import JobResult
from examtwin.services.cache_paths import resolve_markdown_cache_path
from examtwin.services.knowledge import (
    evidence_role_for_source,
    list_knowledge_points,
    match_knowledge_points,
)
from examtwin.services.providers import build_embedding
from examtwin.services.subject_context import SubjectContext
from examtwin.services.vector_index_publication import QdrantIndexPublisher
from examtwin.services.vector_index_reuse import embedding_identity, plan_vector_writes
from examtwin.services.vector_retrieval import (
    HYBRID_INDEX_SCHEMA_VERSION,
    collection_supports_hybrid,
    qdrant_vector_store,
)
from llama_index.core import Document, StorageContext, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import BaseNode, TextNode
from qdrant_client import QdrantClient

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
HTML_TABLE_RE = re.compile(r"(<table\b.*?</table>)", re.IGNORECASE | re.DOTALL)
TABLE_EMBED_CHAR_LIMIT = 16_000
ASSESSMENT_CHUNK_SIZE = 450
ASSESSMENT_CHUNK_OVERLAP = 60
logger = logging.getLogger(__name__)


def _section_documents(
    content: str,
    *,
    id_prefix: str,
    metadata: dict[str, Any],
) -> list[Document]:
    content = re.sub(r"^\s*##\s+Page\s+\d+\s*", "", content, count=1).strip()
    headings = list(HEADING_RE.finditer(content))
    if not headings:
        return [
            Document(
                text=content,
                id_=id_prefix,
                metadata={
                    **metadata,
                    "node_kind": "evidence_chunk",
                    "section": None,
                    "section_path": [],
                },
                excluded_llm_metadata_keys=["document_id"],
            )
        ]

    documents: list[Document] = []
    hierarchy: list[tuple[int, str]] = []
    prefix = content[: headings[0].start()].strip()
    if prefix:
        documents.append(
            Document(
                text=prefix,
                id_=f"{id_prefix}:section:0",
                metadata={
                    **metadata,
                    "node_kind": "evidence_chunk",
                    "section": None,
                    "section_path": [],
                },
                excluded_llm_metadata_keys=["document_id"],
            )
        )
    for index, heading in enumerate(headings, start=1):
        level = len(heading.group(1))
        title = re.sub(r"\s+", " ", heading.group(2)).strip()
        hierarchy = [item for item in hierarchy if item[0] < level]
        hierarchy.append((level, title))
        end = headings[index].start() if index < len(headings) else len(content)
        section_text = content[heading.start() : end].strip()
        if not section_text:
            continue
        section_path = [item[1] for item in hierarchy]
        documents.append(
            Document(
                text=section_text,
                id_=f"{id_prefix}:section:{index}",
                metadata={
                    **metadata,
                    "node_kind": "evidence_chunk",
                    "section": title,
                    "section_path": section_path,
                },
                excluded_llm_metadata_keys=["document_id"],
            )
        )
    return documents


def _documents_with_pages(text: str, row: dict[str, Any]) -> list[Document]:
    common_metadata = {
        "document_id": row["id"],
        "source": row["path"],
        "filename": row["filename"],
        "source_type": row["source_type"],
        "authority_tier": row.get("authority_tier", "supplementary"),
        "pair_key": row["pair_key"] or "",
        "unit_code": row["unit_code"] or "",
        "subject_code": row.get("subject_code") or "9660",
    }
    parts = re.split(r"<!--\s*page(?::|\s)\s*(\d+)\s*-->", text)
    if len(parts) == 1:
        return _section_documents(
            text,
            id_prefix=row["id"],
            metadata=common_metadata,
        )
    prefix = parts[0].strip()
    documents: list[Document] = []
    for offset in range(1, len(parts), 2):
        page = int(parts[offset])
        content = parts[offset + 1].strip()
        if page == 1 and prefix:
            content = f"{prefix}\n\n{content}"
        documents.extend(
            _section_documents(
                content,
                id_prefix=f"{row['id']}:page:{page}",
                metadata={**common_metadata, "page": page},
            )
        )
    return documents


def _evidence_nodes(
    documents: list[Document],
    *,
    splitter: SentenceSplitter | None = None,
    assessment_splitter: SentenceSplitter | None = None,
) -> list[BaseNode]:
    """Split prose normally while keeping each MinerU HTML table as one node."""
    splitter = splitter or SentenceSplitter(chunk_size=900, chunk_overlap=120)
    assessment_splitter = assessment_splitter or SentenceSplitter(
        chunk_size=ASSESSMENT_CHUNK_SIZE,
        chunk_overlap=ASSESSMENT_CHUNK_OVERLAP,
    )
    nodes: list[BaseNode] = []
    for document in documents:
        document_splitter = (
            assessment_splitter
            if document.metadata.get("source_type") in {"question_paper", "mark_scheme"}
            else splitter
        )
        parts = HTML_TABLE_RE.split(document.text)
        if len(parts) == 1:
            document.metadata["block_kind"] = "prose"
            nodes.extend(
                document_splitter.get_nodes_from_documents([document], show_progress=False)
            )
            continue
        for block_index, part in enumerate(parts):
            content = part.strip()
            if not content:
                continue
            metadata = dict(document.metadata)
            if HTML_TABLE_RE.fullmatch(content):
                content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                retrieval_text = _table_retrieval_projection(content)
                metadata.update(
                    {
                        "block_kind": "table",
                        "table_index": block_index,
                        "table_row_count": len(re.findall(r"<tr\b", content, flags=re.IGNORECASE)),
                        "retrieval_text": retrieval_text,
                    }
                )
                nodes.append(
                    TextNode(
                        id_=str(
                            uuid.uuid5(
                                uuid.NAMESPACE_URL,
                                (
                                    "https://examtwin.local/evidence/table/"
                                    f"{document.node_id}/{block_index}/{content_hash}"
                                ),
                            )
                        ),
                        text=content,
                        metadata=metadata,
                        excluded_llm_metadata_keys=["document_id"],
                    )
                )
                continue
            metadata["block_kind"] = "prose"
            prose = Document(
                id_=f"{document.node_id}:prose:{block_index}",
                text=content,
                metadata=metadata,
                excluded_llm_metadata_keys=["document_id"],
            )
            nodes.extend(document_splitter.get_nodes_from_documents([prose], show_progress=False))
    return nodes


def _table_retrieval_projection(
    table_html: str,
    *,
    max_chars: int = TABLE_EMBED_CHAR_LIMIT,
) -> str:
    """Represent every table row within a bounded embedding/rerank input."""
    rows = re.findall(
        r"<tr\b[^>]*>(.*?)</tr>",
        table_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not rows:
        plain = html.unescape(re.sub(r"<[^>]+>", " ", table_html))
        return re.sub(r"\s+", " ", plain).strip()[:max_chars]
    row_budget = max(1, (max_chars - len(rows)) // len(rows))
    projected: list[str] = []
    for row in rows:
        cells = re.findall(
            r"<t[dh]\b[^>]*>(.*?)</t[dh]>",
            row,
            flags=re.IGNORECASE | re.DOTALL,
        )
        values = cells or [row]
        plain_cells = [
            re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()
            for value in values
        ]
        projected.append(" | ".join(item for item in plain_cells if item)[:row_budget])
    return "\n".join(projected)[:max_chars]


def _preembed_oversized_tables(nodes: list[BaseNode], embedding: Any) -> None:
    for node in nodes:
        if node.metadata.get("block_kind") != "table":
            continue
        if len(node.get_content()) <= TABLE_EMBED_CHAR_LIMIT or node.embedding is not None:
            continue
        node.embedding = embedding.get_text_embedding(
            str(node.metadata.get("retrieval_text") or "")[:TABLE_EMBED_CHAR_LIMIT]
        )


def _index_catalog(repository: KnowledgeRepository, subject_code: str) -> list[dict[str, Any]]:
    points = list_knowledge_points(repository, subject_code=subject_code)
    objectives = [
        point for point in points if point["features"].get("node_type") == "learning_objective"
    ]
    return objectives or [
        point for point in points if point["features"].get("node_type") == "topic"
    ]


def _annotate_evidence_nodes(
    nodes: list[BaseNode],
    catalog: list[dict[str, Any]],
) -> None:
    for node in nodes:
        source_type = str(node.metadata.get("source_type") or "")
        threshold = 0.45 if source_type in {"question_paper", "mark_scheme"} else 0.30
        matches = [
            (score, point)
            for score, point in match_knowledge_points(
                node.get_content(),
                catalog,
                limit=3,
            )
            if score >= threshold
        ]
        if not matches:
            node.metadata["knowledge_codes"] = []
            node.metadata["knowledge_match_confidence"] = {}
            continue
        node.metadata["knowledge_codes"] = [point["code"] for _, point in matches]
        node.metadata["knowledge_code"] = matches[0][1]["code"]
        node.metadata["knowledge_match_confidence"] = {
            point["code"]: round(min(1.0, score), 4) for score, point in matches
        }


def _knowledge_point_nodes(catalog: list[dict[str, Any]]) -> list[TextNode]:
    nodes: list[TextNode] = []
    for point in catalog:
        primary = next(
            (
                reference
                for reference in point.get("references", [])
                if reference.get("evidence_role") == "definition"
            ),
            (point.get("references") or [{}])[0],
        )
        relations = "; ".join(
            f"{relation['relation_type']} {relation['direction']} "
            f"{relation['code']} {relation['title']}"
            for relation in point.get("relations", [])
            if relation["relation_type"] != "contains"
        )
        difficulty = point["difficulty"]
        text = "\n".join(
            [
                f"Knowledge point {point['code']}: {point['title']}",
                f"Curriculum path: {point['breadcrumb']}",
                f"Learning objective: {point['definition']}",
                (
                    f"Difficulty: {difficulty['score']:.4f} {difficulty['label']}; "
                    f"confidence {difficulty['confidence']:.2f}; "
                    f"evidence level {difficulty['evidence_level']}. "
                    f"{difficulty['rationale']}"
                ),
                f"Relations: {relations or 'No non-hierarchical relation recorded.'}",
            ]
        )
        metadata = {
            "node_kind": "knowledge_point",
            "knowledge_code": point["code"],
            "knowledge_codes": [point["code"]],
            "knowledge_title": point["title"],
            "knowledge_definition": point["definition"],
            "knowledge_breadcrumb": point["breadcrumb"],
            "document_id": primary.get("document_id"),
            "source": primary.get("source") or point["source_ref"],
            "filename": Path(str(primary.get("source") or point["source_ref"])).name,
            "source_type": primary.get("source_type") or "syllabus",
            "authority_tier": primary.get("authority_tier") or "official",
            "pair_key": primary.get("pair_key") or "",
            "unit_code": point["unit_code"],
            "subject_code": str(point["id"]).split(":", 1)[0],
            "page": primary.get("page"),
            "section": primary.get("section") or point["title"],
            "section_path": primary.get("section_path")
            or [item["title"] for item in point["path"]],
        }
        nodes.append(
            TextNode(
                id_=str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"https://examtwin.local/knowledge/{point['id']}",
                    )
                ),
                text=text,
                metadata=metadata,
                excluded_llm_metadata_keys=["document_id"],
            )
        )
    return nodes


def _persist_index_evidence(
    repository: KnowledgeRepository,
    nodes: list[BaseNode],
    *,
    subject_code: str,
    build_id: str,
) -> None:
    now = utcnow()
    evidence: list[dict[str, Any]] = []
    for node in nodes:
        metadata = node.metadata
        if metadata.get("node_kind") != "evidence_chunk":
            continue
        document_id = metadata.get("document_id")
        codes = metadata.get("knowledge_codes") or []
        if not document_id or not codes:
            continue
        excerpt = re.sub(r"\s+", " ", node.get_content()).strip()
        if len(excerpt) < 30:
            continue
        excerpt = excerpt[:4000]
        page = metadata.get("page")
        try:
            page = int(page) if page is not None else None
        except (TypeError, ValueError):
            page = None
        section = str(metadata.get("section") or "")
        section_path = metadata.get("section_path") or []
        if isinstance(section_path, str):
            section_path = [section_path]
        source = str(metadata.get("source") or "")
        source_ref = f"{source}#page={page}" if page is not None else source
        role = evidence_role_for_source(metadata.get("source_type"), section)
        confidences = metadata.get("knowledge_match_confidence") or {}
        content_hash = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
        for code in codes:
            evidence.append(
                {
                    "knowledge_point_id": (
                        f"{metadata.get('subject_code') or subject_code}:{code}"
                    ),
                    "source_document_id": document_id,
                    "page": page,
                    "section": section,
                    "section_path_json": json.dumps(section_path, ensure_ascii=False),
                    "evidence_role": role,
                    "excerpt": excerpt,
                    "content_hash": content_hash,
                    "confidence": float(confidences.get(code, 0.3)),
                    "source_ref": source_ref,
                    "created_at": now,
                }
            )
    repository.stage_index_evidence(
        subject_code=subject_code,
        build_id=build_id,
        evidence=evidence,
    )


def build_vector_index(
    settings: Settings,
    subject: SubjectContext,
    repository: VectorIndexRepository,
    knowledge_repository: KnowledgeRepository,
    *,
    limit: int | None = None,
    embedding: Any | None = None,
    resume: bool = False,
) -> JobResult:
    if limit is not None:
        raise ValueError(
            "Partial vector indexes cannot be published to the live alias; "
            "convert a bounded corpus first, then run a complete index build."
        )
    subject_pack = subject.pack
    rows = repository.indexable_documents(
        subject_code=subject_pack.subject_code,
        limit=limit,
    )
    client = QdrantClient(url=settings.qdrant_url)
    publisher = QdrantIndexPublisher(
        client,
        base_collection=settings.qdrant_collection,
        alias_name=settings.qdrant_collection_alias,
    )
    previous_collection = publisher.alias_target()
    if previous_collection is None and client.collection_exists(settings.qdrant_collection):
        previous_collection = publisher.bootstrap_alias()

    resumable = (
        repository.latest_resumable(
            subject_code=subject_pack.subject_code,
            alias_name=settings.qdrant_collection_alias,
        )
        if resume
        else None
    )
    if resume and resumable is None:
        raise LookupError("No failed or interrupted vector index build is available to resume")
    run_id = str(resumable["id"]) if resumable else str(uuid.uuid4())
    staging_collection = (
        str(resumable["staging_collection"]) if resumable else publisher.staging_name(run_id)
    )
    hybrid_index = not client.collection_exists(staging_collection) or collection_supports_hybrid(
        client, staging_collection
    )
    now = utcnow()
    if resumable:
        repository.update_run(
            run_id,
            {
                "status": "running",
                "stage": "loading_documents",
                "error": None,
                "updated_at": now,
            },
        )
    else:
        repository.create_run(
            {
                "id": run_id,
                "subject_code": subject_pack.subject_code,
                "alias_name": settings.qdrant_collection_alias,
                "staging_collection": staging_collection,
                "previous_collection": previous_collection,
                "status": "running",
                "stage": "loading_documents",
                "input_hash": None,
                "expected_points": 0,
                "indexed_points": 0,
                "document_count": len(rows),
                "error": None,
                "created_at": now,
                "updated_at": now,
                "published_at": None,
            }
        )

    try:
        documents: list[Document] = []
        errors: list[str] = []
        for row in rows:
            try:
                markdown_path = resolve_markdown_cache_path(
                    settings,
                    str(row["id"]),
                    str(row["markdown_path"]),
                )
                text = markdown_path.read_text(encoding="utf-8")
                documents.extend(_documents_with_pages(text, row))
            except Exception as error:
                errors.append(f"{row['filename']}: {error}")
        if errors:
            raise ValueError(
                "Vector index input gate failed; unreadable Markdown: " + "; ".join(errors[:10])
            )
        if not documents:
            raise ValueError("Vector index input gate failed: no indexable documents")

        evidence_nodes = _evidence_nodes(documents)
        catalog = _index_catalog(knowledge_repository, subject_pack.subject_code)
        _annotate_evidence_nodes(evidence_nodes, catalog)
        nodes: list[BaseNode] = [*evidence_nodes, *_knowledge_point_nodes(catalog)]
        index_schema_version = HYBRID_INDEX_SCHEMA_VERSION if hybrid_index else "dense-v0"
        embed_identity = embedding_identity(
            base_url=settings.siliconflow_base_url,
            model=settings.embedding_model,
        )
        input_hash = hashlib.sha256(
            json.dumps(
                {
                    "documents": [
                        (row["id"], row["checksum"], row["markdown_path"]) for row in rows
                    ],
                    "index_schema_version": index_schema_version,
                    "embedding_identity": embed_identity,
                    "chunk_policy": {
                        "general_size": 900,
                        "general_overlap": 120,
                        "assessment_size": ASSESSMENT_CHUNK_SIZE,
                        "assessment_overlap": ASSESSMENT_CHUNK_OVERLAP,
                        "table_projection_limit": TABLE_EMBED_CHAR_LIMIT,
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if resumable and resumable.get("input_hash") not in (None, input_hash):
            raise ValueError("Cannot resume vector index build because its inputs changed")
        repository.update_run(
            run_id,
            {
                "stage": "embedding",
                "input_hash": input_hash,
                "expected_points": len(nodes),
                "document_count": len(rows),
                "updated_at": utcnow(),
            },
        )

        if client.collection_exists(staging_collection):
            if not resume:
                raise ValueError(
                    f"Refusing to overwrite existing staging collection: {staging_collection}"
                )
        model = embedding or build_embedding(settings)
        write_plan = plan_vector_writes(
            client,
            nodes,
            staging_collection=staging_collection,
            previous_collection=previous_collection,
            build_id=run_id,
            schema_version=index_schema_version,
            embed_identity=embed_identity,
        )
        logger.info(
            "vector_index_embedding_plan",
            extra={
                "subject_code": subject_pack.subject_code,
                "build_id": run_id,
                "points": len(nodes),
                "resumed_points": write_plan.resumed_points,
                "reused_embeddings": write_plan.reused_embeddings,
                "embeddings_required": write_plan.embeddings_required,
            },
        )
        vector_store = qdrant_vector_store(
            client,
            staging_collection,
            hybrid=hybrid_index,
        )
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        remaining_nodes = write_plan.pending_nodes
        if remaining_nodes:
            _preembed_oversized_tables(remaining_nodes, model)
            VectorStoreIndex(
                remaining_nodes,
                storage_context=storage_context,
                embed_model=model,
                insert_batch_size=512,
                show_progress=True,
            )

        gate = publisher.validate(staging_collection, len(nodes))
        repository.update_run(
            run_id,
            {
                "stage": "publishing",
                "indexed_points": gate.indexed_points,
                "updated_at": utcnow(),
            },
        )
        _persist_index_evidence(
            knowledge_repository,
            evidence_nodes,
            subject_code=subject_pack.subject_code,
            build_id=run_id,
        )
        publisher.publish(staging_collection, len(nodes))
        published_at = utcnow()
        repository.finalize_publication(
            run_id=run_id,
            subject_code=subject_pack.subject_code,
            alias_name=settings.qdrant_collection_alias,
            collection_name=staging_collection,
            indexed_points=gate.indexed_points,
            document_ids=[str(row["id"]) for row in rows],
            published_at=published_at,
        )
        return JobResult(processed=len(rows), succeeded=len(rows), failed=0)
    except Exception as error:
        repository.update_run(
            run_id,
            {
                "status": "failed",
                "stage": "failed",
                "error": str(error)[:2000],
                "updated_at": utcnow(),
            },
        )
        raise


def load_vector_index(settings: Settings, embedding: Any | None = None) -> VectorStoreIndex:
    client = QdrantClient(url=settings.qdrant_url)
    if not client.collection_exists(settings.qdrant_collection_alias):
        raise FileNotFoundError("Qdrant collection is not built. Run `uv run examtwin index`.")
    vector_store = qdrant_vector_store(
        client,
        settings.qdrant_collection_alias,
        hybrid=collection_supports_hybrid(client, settings.qdrant_collection_alias),
    )
    return VectorStoreIndex.from_vector_store(
        vector_store,
        embed_model=embedding or build_embedding(settings),
    )
