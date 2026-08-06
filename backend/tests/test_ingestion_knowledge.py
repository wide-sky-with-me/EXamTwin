import uuid

from examtwin.knowledge.ingestion import (
    TABLE_EMBED_CHAR_LIMIT,
    _documents_with_pages,
    _evidence_nodes,
    _knowledge_point_nodes,
    _preembed_oversized_tables,
)
from llama_index.core import Document


def _row() -> dict:
    return {
        "id": "doc-1",
        "path": "book.md",
        "filename": "book.md",
        "source_type": "textbook",
        "authority_tier": "licensed_core",
        "pair_key": None,
        "unit_code": "P2",
    }


def test_section_provenance_does_not_invent_a_page() -> None:
    documents = _documents_with_pages(
        "# Integration\n\n## Worked example\n\nUse integration by parts.",
        _row(),
    )

    worked_example = documents[-1]
    assert "page" not in worked_example.metadata
    assert worked_example.metadata["section"] == "Worked example"
    assert worked_example.metadata["section_path"] == [
        "Integration",
        "Worked example",
    ]
    assert worked_example.metadata["node_kind"] == "evidence_chunk"


def test_physical_page_is_kept_only_when_a_real_marker_exists() -> None:
    documents = _documents_with_pages(
        "<!-- page:7 -->\n\n# Integration\n\nA source paragraph.",
        _row(),
    )

    assert documents[0].metadata["page"] == 7
    assert documents[0].metadata["section"] == "Integration"


def test_knowledge_point_nodes_use_qdrant_compatible_stable_uuid_ids() -> None:
    point = {
        "id": "9660:P2.1.O01",
        "code": "P2.1.O01",
        "title": "Integration by substitution",
        "unit_code": "P2",
        "definition": "Use substitution to evaluate integrals.",
        "breadcrumb": "Mathematics > Pure 2 > Integration",
        "path": [{"title": "Mathematics"}, {"title": "Integration"}],
        "relations": [],
        "difficulty": {
            "score": 0.62,
            "label": "medium",
            "confidence": 0.3,
            "evidence_level": "D",
            "rationale": "Cold-start curriculum estimate.",
        },
        "references": [],
        "source_ref": "9660 syllabus",
    }

    first = _knowledge_point_nodes([point])[0]
    second = _knowledge_point_nodes([point])[0]

    assert uuid.UUID(first.node_id)
    assert first.node_id == second.node_id


def _oversized_mineru_table() -> str:
    return (
        "<table><tr><td>Content</td><td>Additional information</td></tr>"
        + "".join(
            (
                f"<tr><td>Objective {index:04d}</td>"
                f"<td>Detail {index:04d} "
                "with enough explanatory text to exceed the embedding limit."
                "</td></tr>"
            )
            for index in range(480)
        )
        + "</table>"
    )


def test_oversized_mineru_html_table_is_atomic_between_prose_nodes() -> None:
    table = _oversized_mineru_table()
    assert len(table) > TABLE_EMBED_CHAR_LIMIT
    document = Document(
        id_="doc-1:section:table",
        text=(
            "Unique introductory prose before the table.\n\n"
            f"{table}\n\n"
            "Unique closing prose after the table."
        ),
        metadata={"node_kind": "evidence_chunk", "section": "Objectives"},
    )

    nodes = _evidence_nodes([document])
    table_nodes = [node for node in nodes if node.metadata["block_kind"] == "table"]
    prose_text = "\n".join(
        node.get_content() for node in nodes if node.metadata["block_kind"] == "prose"
    )

    assert len(table_nodes) == 1
    assert table_nodes[0].get_content() == table
    assert table_nodes[0].metadata["table_row_count"] == 481
    assert "Objective 0000" in table_nodes[0].metadata["retrieval_text"]
    assert "Objective 0479" in table_nodes[0].metadata["retrieval_text"]
    assert len(table_nodes[0].metadata["retrieval_text"]) <= TABLE_EMBED_CHAR_LIMIT
    assert uuid.UUID(table_nodes[0].node_id)
    assert "Unique introductory prose before the table." in prose_text
    assert "Unique closing prose after the table." in prose_text
    assert "Unique introductory prose" not in table_nodes[0].get_content()
    assert "Unique closing prose" not in table_nodes[0].get_content()


def test_oversized_table_embedding_uses_projection_without_mutating_source() -> None:
    table = _oversized_mineru_table()
    document = Document(
        id_="doc-1:section:table",
        text=f"Before.\n\n{table}\n\nAfter.",
        metadata={"node_kind": "evidence_chunk", "section": "Objectives"},
    )
    nodes = _evidence_nodes([document])
    table_node = next(node for node in nodes if node.metadata["block_kind"] == "table")
    original_content = table_node.get_content()
    retrieval_projection = table_node.metadata["retrieval_text"]

    class RecordingEmbedding:
        def __init__(self) -> None:
            self.inputs: list[str] = []

        def get_text_embedding(self, text: str) -> list[float]:
            self.inputs.append(text)
            return [0.1, 0.2, 0.3]

    embedding = RecordingEmbedding()
    _preembed_oversized_tables(nodes, embedding)

    assert embedding.inputs == [retrieval_projection]
    assert len(embedding.inputs[0]) <= TABLE_EMBED_CHAR_LIMIT
    assert table_node.embedding == [0.1, 0.2, 0.3]
    assert table_node.get_content() == original_content == table
