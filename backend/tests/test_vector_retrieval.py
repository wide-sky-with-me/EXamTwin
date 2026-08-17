from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from examtwin.assessment.rag import RagService
from examtwin.knowledge.retrieval_trace_repository import RetrievalTraceRepository
from examtwin.knowledge.vector_index_reuse import (
    embedding_identity,
    plan_vector_writes,
    prune_stale_points,
)
from examtwin.knowledge.vector_retrieval import (
    lexical_sparse_encoder,
    qdrant_vector_store,
    retrieval_filters,
)
from examtwin.platform.config import Settings
from examtwin.platform.database.models import RetrievalTraceModel
from examtwin.subjects.public import subject_context
from llama_index.core.schema import NodeWithScore, TextNode
from llama_index.core.vector_stores.types import VectorStoreQuery, VectorStoreQueryMode
from qdrant_client import QdrantClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def _node(text: str, *, subject: str, unit: str) -> TextNode:
    node = TextNode(
        id_=str(uuid.uuid4()),
        text=text,
        metadata={
            "subject_code": subject,
            "unit_code": unit,
            "source_type": "mark_scheme",
            "authority_tier": "official",
            "node_kind": "evidence_chunk",
        },
    )
    node.embedding = [1.0, 0.0]
    return node


def test_hybrid_qdrant_search_prefilters_before_dense_and_lexical_fusion() -> None:
    client = QdrantClient(":memory:")
    store = qdrant_vector_store(client, "hybrid", hybrid=True)
    store.add(
        [
            _node("Use the binomial critical region.", subject="9660", unit="P1"),
            _node("Use the binomial critical region.", subject="9660", unit=""),
            _node("Unrelated calculus wording.", subject="9660", unit="P2"),
            _node("Use the binomial critical region.", subject="9640", unit="U1"),
        ]
    )

    result = store.query(
        VectorStoreQuery(
            query_embedding=[1.0, 0.0],
            query_str="binomial critical region",
            similarity_top_k=10,
            sparse_top_k=10,
            hybrid_top_k=10,
            mode=VectorStoreQueryMode.HYBRID,
            filters=retrieval_filters(
                subject_code="9660",
                unit_code="P1",
                source_types=("mark_scheme",),
                authority_tiers=("official",),
            ),
        )
    )

    assert result.nodes is not None
    assert {node.metadata["subject_code"] for node in result.nodes} == {"9660"}
    assert {node.metadata["unit_code"] for node in result.nodes} == {"", "P1"}


def test_hybrid_unit_filter_allows_cross_unit_knowledge_point_only() -> None:
    client = QdrantClient(":memory:")
    store = qdrant_vector_store(client, "synoptic", hybrid=True)
    catalog = _node("Characteristics and functions of money.", subject="9640", unit="U2")
    catalog.metadata.update(
        node_kind="knowledge_point",
        source_role="core_knowledge",
        source_type="syllabus",
    )
    excluded_evidence = _node(
        "Unrelated evidence from another unit.",
        subject="9640",
        unit="U2",
    )
    excluded_evidence.metadata.update(
        source_role="core_knowledge",
        source_type="syllabus",
    )
    store.add([catalog, excluded_evidence])

    result = store.query(
        VectorStoreQuery(
            query_embedding=[1.0, 0.0],
            query_str="functions of money",
            similarity_top_k=10,
            sparse_top_k=10,
            hybrid_top_k=10,
            mode=VectorStoreQueryMode.HYBRID,
            filters=retrieval_filters(
                subject_code="9640",
                unit_code="U4",
                source_types=("syllabus",),
                authority_tiers=("official",),
                source_roles=("core_knowledge",),
            ),
        )
    )

    assert result.nodes is not None
    assert [node.metadata["node_kind"] for node in result.nodes] == ["knowledge_point"]


def test_catalog_filter_selects_only_direct_knowledge_points() -> None:
    client = QdrantClient(":memory:")
    store = qdrant_vector_store(client, "catalog", hybrid=True)
    catalog = _node("Monetary policy involves the central bank.", subject="9640", unit="U2")
    catalog.metadata.update(
        node_kind="knowledge_point",
        source_role="core_knowledge",
        source_type="syllabus",
    )
    evidence = _node("Monetary policy evidence.", subject="9640", unit="U4")
    evidence.metadata.update(source_role="core_knowledge", source_type="syllabus")
    store.add([catalog, evidence])

    result = store.query(
        VectorStoreQuery(
            query_str="monetary policy central bank",
            similarity_top_k=10,
            sparse_top_k=10,
            mode=VectorStoreQueryMode.SPARSE,
            filters=retrieval_filters(
                subject_code="9640",
                source_roles=("core_knowledge",),
                node_kinds=("knowledge_point",),
            ),
        )
    )

    assert result.nodes is not None
    assert [node.metadata["node_kind"] for node in result.nodes] == ["knowledge_point"]


def test_lexical_sparse_encoder_is_deterministic_and_phrase_sensitive() -> None:
    first = lexical_sparse_encoder(["hence show that critical region"])
    second = lexical_sparse_encoder(["hence show that critical region"])
    different = lexical_sparse_encoder(["differentiate the polynomial"])

    assert first == second
    assert first[0][0]
    assert set(first[0][0]).isdisjoint(different[0][0])


def test_vector_write_plan_stabilizes_prose_ids_and_reuses_matching_dense_vectors() -> None:
    client = QdrantClient(":memory:")
    identity = embedding_identity(base_url="https://embedding.test/v1", model="embed-8b")
    first = _node("A stable prose chunk.", subject="9660", unit="P1")
    first.metadata["block_kind"] = "prose"
    first_plan = plan_vector_writes(
        client,
        [first],
        staging_collection="first",
        previous_collection=None,
        build_id="build-1",
        schema_version="schema-v1",
        embed_identity=identity,
    )
    store = qdrant_vector_store(client, "first", hybrid=True)
    store.add(first_plan.pending_nodes)

    second = _node("A stable prose chunk.", subject="9660", unit="P1")
    second.metadata["block_kind"] = "prose"
    second.embedding = None
    second_plan = plan_vector_writes(
        client,
        [second],
        staging_collection="second",
        previous_collection="first",
        build_id="build-2",
        schema_version="schema-v1",
        embed_identity=identity,
    )

    assert second.node_id == first.node_id
    assert second_plan.reused_embeddings == 1
    assert second_plan.embeddings_required == 0
    assert second.embedding == [1.0, 0.0]
    assert second.metadata["index_build_id"] == "build-2"


def test_vector_write_plan_reuses_dense_vectors_across_sparse_schema_upgrade() -> None:
    client = QdrantClient(":memory:")
    identity = embedding_identity(base_url="https://embedding.test/v1", model="embed-8b")
    first = _node("Stable embedding content.", subject="9660", unit="P1")
    first.metadata["block_kind"] = "prose"
    first_plan = plan_vector_writes(
        client,
        [first],
        staging_collection="first",
        previous_collection=None,
        build_id="build-1",
        schema_version="schema-v1",
        embed_identity=identity,
    )
    qdrant_vector_store(client, "first", hybrid=True).add(first_plan.pending_nodes)

    second = _node("Stable embedding content.", subject="9660", unit="P1")
    second.metadata["block_kind"] = "prose"
    second.embedding = None
    second_plan = plan_vector_writes(
        client,
        [second],
        staging_collection="second",
        previous_collection="first",
        build_id="build-2",
        schema_version="schema-v2",
        embed_identity=identity,
    )

    assert second_plan.reused_embeddings == 1
    assert second_plan.embeddings_required == 0
    assert second.embedding == [1.0, 0.0]
    assert second.metadata["index_schema_version"] == "schema-v2"


def test_vector_write_plan_ignores_filter_only_source_role_for_embedding_reuse() -> None:
    client = QdrantClient(":memory:")
    identity = embedding_identity(base_url="https://embedding.test/v1", model="embed-8b")
    first = _node("Stable curriculum objective.", subject="9660", unit="P1")
    first.metadata["node_kind"] = "knowledge_point"
    first_plan = plan_vector_writes(
        client,
        [first],
        staging_collection="first",
        previous_collection=None,
        build_id="build-1",
        schema_version="schema-v1",
        embed_identity=identity,
    )
    qdrant_vector_store(client, "first", hybrid=True).add(first_plan.pending_nodes)

    second = _node("Stable curriculum objective.", subject="9660", unit="P1")
    second.id_ = first.node_id
    second.metadata.update(node_kind="knowledge_point", source_role="core_knowledge")
    second.embedding = None
    second_plan = plan_vector_writes(
        client,
        [second],
        staging_collection="second",
        previous_collection="first",
        build_id="build-2",
        schema_version="schema-v2",
        embed_identity=identity,
    )

    assert second_plan.reused_embeddings == 1
    assert second_plan.embeddings_required == 0
    assert second.embedding == [1.0, 0.0]


def test_prose_identity_ignores_run_local_navigation_ids() -> None:
    client = QdrantClient(":memory:")
    identity = embedding_identity(base_url="https://embedding.test/v1", model="embed-8b")
    first = _node("A linked prose chunk.", subject="9660", unit="P1")
    first.metadata.update(
        block_kind="prose",
        parent_block_id=str(uuid.uuid4()),
        previous_block_id=str(uuid.uuid4()),
        next_block_id=str(uuid.uuid4()),
    )
    plan_vector_writes(
        client,
        [first],
        staging_collection="first",
        previous_collection=None,
        build_id="build-1",
        schema_version="schema-v1",
        embed_identity=identity,
    )

    second = _node("A linked prose chunk.", subject="9660", unit="P1")
    second.metadata.update(
        block_kind="prose",
        parent_block_id=str(uuid.uuid4()),
        previous_block_id=str(uuid.uuid4()),
        next_block_id=str(uuid.uuid4()),
    )
    plan_vector_writes(
        client,
        [second],
        staging_collection="second",
        previous_collection=None,
        build_id="build-2",
        schema_version="schema-v1",
        embed_identity=identity,
    )

    assert second.node_id == first.node_id
    assert second.metadata["node_fingerprint"] == first.metadata["node_fingerprint"]


def test_vector_write_plan_does_not_reuse_a_different_embedding_model() -> None:
    client = QdrantClient(":memory:")
    first = _node("Same content, old embedding.", subject="9660", unit="P1")
    first.metadata["block_kind"] = "prose"
    old_identity = embedding_identity(base_url="https://embedding.test/v1", model="old")
    first_plan = plan_vector_writes(
        client,
        [first],
        staging_collection="first",
        previous_collection=None,
        build_id="build-1",
        schema_version="schema-v1",
        embed_identity=old_identity,
    )
    qdrant_vector_store(client, "first", hybrid=True).add(first_plan.pending_nodes)

    second = _node("Same content, old embedding.", subject="9660", unit="P1")
    second.metadata["block_kind"] = "prose"
    second.embedding = None
    plan = plan_vector_writes(
        client,
        [second],
        staging_collection="second",
        previous_collection="first",
        build_id="build-2",
        schema_version="schema-v1",
        embed_identity=embedding_identity(base_url="https://embedding.test/v1", model="new"),
    )

    assert plan.reused_embeddings == 0
    assert plan.embeddings_required == 1


def test_vector_write_plan_resumes_by_node_identity_not_collection_offset() -> None:
    client = QdrantClient(":memory:")
    identity = embedding_identity(base_url="https://embedding.test/v1", model="embed")
    first = _node("First chunk.", subject="9660", unit="P1")
    first.metadata["block_kind"] = "prose"
    second = _node("Second chunk.", subject="9660", unit="P1")
    second.metadata["block_kind"] = "prose"
    initial = plan_vector_writes(
        client,
        [first, second],
        staging_collection="staging",
        previous_collection=None,
        build_id="build",
        schema_version="schema-v1",
        embed_identity=identity,
    )
    qdrant_vector_store(client, "staging", hybrid=True).add([initial.pending_nodes[1]])

    resumed_first = _node("First chunk.", subject="9660", unit="P1")
    resumed_first.metadata["block_kind"] = "prose"
    resumed_second = _node("Second chunk.", subject="9660", unit="P1")
    resumed_second.metadata["block_kind"] = "prose"
    resumed = plan_vector_writes(
        client,
        [resumed_first, resumed_second],
        staging_collection="staging",
        previous_collection=None,
        build_id="build",
        schema_version="schema-v1",
        embed_identity=identity,
    )

    assert resumed.resumed_points == 1
    assert [node.get_content() for node in resumed.pending_nodes] == ["First chunk."]


def test_resume_prunes_points_that_are_no_longer_in_the_build() -> None:
    client = QdrantClient(":memory:")
    identity = embedding_identity(base_url="https://embedding.test/v1", model="embed")
    retained = _node("Retained chunk.", subject="9660", unit="P1")
    retained.metadata["block_kind"] = "prose"
    stale = _node("Stale chunk.", subject="9660", unit="P1")
    stale.metadata["block_kind"] = "prose"
    initial = plan_vector_writes(
        client,
        [retained, stale],
        staging_collection="staging",
        previous_collection=None,
        build_id="build",
        schema_version="schema-v1",
        embed_identity=identity,
    )
    qdrant_vector_store(client, "staging", hybrid=True).add(initial.pending_nodes)

    assert prune_stale_points(client, "staging", [retained.node_id]) == 1
    records, _ = client.scroll("staging", limit=10, with_payload=False, with_vectors=False)
    assert [str(record.id) for record in records] == [retained.node_id]


def test_cards_keep_unmapped_reranked_evidence_as_raw_fallback() -> None:
    service = RagService(
        Settings(retrieval_raw_fallback_count=2),
        subject_context(Settings()),
        final_answer_provider=object(),
    )
    represented = NodeWithScore(
        node=TextNode(
            text="Mapped evidence",
            metadata={"node_kind": "evidence_chunk", "document_id": "doc-1", "page": 2},
        ),
        score=0.9,
    )
    unmapped = NodeWithScore(
        node=TextNode(
            text="Correct but unmapped evidence",
            metadata={"node_kind": "evidence_chunk", "document_id": "doc-2", "page": 4},
        ),
        score=0.8,
    )

    fallbacks = service._raw_fallbacks(
        [represented, unmapped],
        [{"references": [{"document_id": "doc-1", "page": 2, "section": None}]}],
    )

    assert [node.node.metadata["document_id"] for node in fallbacks] == ["doc-2"]


def test_cards_without_evidence_in_the_requested_source_scope_are_removed() -> None:
    cards = [
        {
            "id": "9660:P1.1.O01",
            "references": [
                {
                    "document_id": "syllabus",
                    "source_type": "syllabus",
                    "authority_tier": "official",
                    "pair_key": None,
                }
            ],
        },
        {
            "id": "9660:P1.1.O02",
            "references": [
                {
                    "document_id": "mark-scheme",
                    "source_type": "mark_scheme",
                    "authority_tier": "official",
                    "pair_key": "9660:2026:JAN:P1",
                },
                {
                    "document_id": "textbook",
                    "source_type": "textbook",
                    "authority_tier": "supplementary",
                    "pair_key": None,
                },
            ],
        },
    ]

    scoped = RagService._filter_cards_to_scope(
        cards,
        pair_key="9660:2026:JAN:P1",
        source_types={"mark_scheme"},
        authority_tiers={"official"},
    )

    assert [card["id"] for card in scoped] == ["9660:P1.1.O02"]
    assert [reference["document_id"] for reference in scoped[0]["references"]] == ["mark-scheme"]


def test_retrieval_trace_repository_separates_subjects_and_keeps_metrics() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    RetrievalTraceModel.__table__.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    repository = RetrievalTraceRepository(sessions)
    now = datetime(2026, 8, 5, tzinfo=UTC)
    base = {
        "query_hash": "hash",
        "query_text": "critical region",
        "filters_json": "{}",
        "retrieval_mode": "hybrid",
        "candidate_limit": 20,
        "candidate_count": 12,
        "postfilter_count": 12,
        "reranked_count": 7,
        "card_count": 4,
        "raw_fallback_count": 2,
        "result_count": 6,
        "index_build_id": "build",
        "result_json": json.dumps([{"document_id": "doc"}]),
        "duration_ms": 42.0,
        "status": "succeeded",
        "error": None,
        "created_at": now,
    }
    repository.record({"id": "math", "subject_code": "9660", **base})
    repository.record({"id": "economics", "subject_code": "9640", **base})

    rows = repository.recent(subject_code="9660")

    assert [row["id"] for row in rows] == ["math"]
    assert rows[0]["candidate_count"] == 12


def test_retrieval_trace_repository_prunes_each_subject_independently() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    RetrievalTraceModel.__table__.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    repository = RetrievalTraceRepository(sessions, max_rows_per_subject=2)
    now = datetime(2026, 8, 5, tzinfo=UTC)
    base = {
        "query_hash": "hash",
        "query_text": "query",
        "filters_json": "{}",
        "retrieval_mode": "hybrid",
        "candidate_limit": 20,
        "candidate_count": 1,
        "postfilter_count": 1,
        "reranked_count": 1,
        "card_count": 1,
        "raw_fallback_count": 0,
        "result_count": 1,
        "index_build_id": "build",
        "result_json": "[]",
        "duration_ms": 1.0,
        "status": "succeeded",
        "error": None,
        "created_at": now,
    }
    for trace_id in ("math-1", "math-2", "math-3"):
        repository.record({"id": trace_id, "subject_code": "9660", **base})
    repository.record({"id": "economics-1", "subject_code": "9640", **base})

    assert [row["id"] for row in repository.recent(subject_code="9660")] == [
        "math-3",
        "math-2",
    ]
    assert [row["id"] for row in repository.recent(subject_code="9640")] == ["economics-1"]
