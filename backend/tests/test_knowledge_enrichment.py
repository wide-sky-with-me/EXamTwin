from datetime import UTC, datetime

from examtwin.knowledge.knowledge_repository import KnowledgeRepository
from examtwin.knowledge.publication import extract_syllabus_objectives
from examtwin.knowledge.queries import (
    build_retrieval_cards,
    list_knowledge_points,
    match_knowledge_points,
)
from examtwin.platform.database.models import (
    Base,
    KnowledgeEvidenceModel,
    KnowledgePointModel,
    KnowledgeRelationModel,
    SourceDocumentModel,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def test_extract_syllabus_objectives_builds_stable_child_codes() -> None:
    markdown = """
## Page 22
P2.7: Integration
<table>
<tr><td>Content</td><td>Additional information</td></tr>
<tr><td>Integration by parts.</td><td>Reverse of the product rule.</td></tr>
<tr><td>Evaluation of a volume of revolution.</td><td>About either coordinate axis.</td></tr>
</table>
## Page 23
P2.8: Differential equations
<table>
<tr><td>Content</td><td>Additional information</td></tr>
<tr><td>Formation of a differential equation.</td><td>Simple models.</td></tr>
</table>
"""

    objectives = extract_syllabus_objectives(markdown)

    assert [item["code"] for item in objectives] == [
        "P2.7.O01",
        "P2.7.O02",
        "P2.8.O01",
    ]
    assert objectives[0]["parent"] == "P2.7"
    assert objectives[0]["description"] == "Reverse of the product rule."
    assert objectives[2]["page"] == 23


def test_integration_objective_fragments_are_reader_facing_titles() -> None:
    objectives = extract_syllabus_objectives(
        """
## Page 22
P2.7: Integration
<table>
<tr><td>Content</td><td>Additional information</td></tr>
<tr><td>by substitution;</td><td>A worked example.</td></tr>
<tr><td>and integration by parts.</td><td>Reverse product rule.</td></tr>
<tr><td>These methods as the reverse processes.</td><td>Use reverse rules.</td></tr>
</table>
"""
    )

    assert [item["title"] for item in objectives] == [
        "Integration by substitution.",
        "Integration by parts.",
        ("Integration methods as the reverse processes."),
    ]


def test_objective_text_repairs_clear_mineru_word_boundaries() -> None:
    objectives = extract_syllabus_objectives(
        """
## Page 18
M1.3: Forces and Newton's laws
<table>
<tr><td>Content</td><td>Additional information</td></tr>
<tr><td>Rods.Normal reactions.</td><td>willnotbe required.</td></tr>
</table>
## Page 22
P2.8: Differential equations
<table>
<tr><td>Content</td><td>Additional information</td></tr>
<tr><td>Differential equations.</td><td>Interpretation asthe rate:it isnotrequired.</td></tr>
</table>
"""
    )

    assert objectives[0]["title"] == ("Rods. Normal reactions.")
    assert objectives[0]["description"] == "will not be required."
    assert objectives[1]["description"] == ("Interpretation as the rate: it is not required.")


def test_context_dependent_titles_are_made_self_contained() -> None:
    objectives = extract_syllabus_objectives(
        """
## Page 25
S2.2: Continuous random variables
<table><tr><td>Differences from discrete random variables.</td><td></td></tr></table>
## Page 29
M2.4: Newton's law of motion
<table><tr><td>Application to situations, with variable acceleration.</td><td></td></tr></table>
"""
    )

    assert [item["title"] for item in objectives] == [
        "Differences between continuous and discrete random variables.",
        "Applications of Newton's laws to motion with variable acceleration.",
    ]


def test_objective_extraction_stops_before_non_curriculum_tables() -> None:
    objectives = extract_syllabus_objectives(
        """
## Page 29
M2.7: Uniform circular motion
<table>
<tr><td>Content</td><td>Additional information</td></tr>
<tr><td>Conical pendulum.</td><td></td></tr>
</table>
## Page 30
## 4 Scheme of assessment
<table>
<tr><td>June 2019</td><td>√</td></tr>
<tr><td>Overall weighting of units (%)</td><td>20</td></tr>
</table>
"""
    )

    assert [(item["code"], item["title"]) for item in objectives] == [
        ("M2.7.O01", "Conical pendulum.")
    ]


def make_knowledge_repository() -> KnowledgeRepository:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    now = datetime(2026, 8, 3, tzinfo=UTC)
    points = [
        {
            "id": "9660:ROOT",
            "code": "ROOT",
            "title": "Mathematics 9660",
            "unit_code": "9660",
            "strand": "Subject",
            "parent_id": None,
            "difficulty_score": 0.5,
            "difficulty_label": "medium",
            "difficulty_confidence": 1.0,
            "evidence_level": "A",
            "source_ref": "spec.pdf#page=3",
            "features_json": '{"node_type":"subject"}',
            "updated_at": now,
        },
        {
            "id": "9660:P2",
            "code": "P2",
            "title": "Pure Mathematics 2",
            "unit_code": "P2",
            "strand": "Pure",
            "parent_id": "9660:ROOT",
            "difficulty_score": 0.5,
            "difficulty_label": "medium",
            "difficulty_confidence": 0.7,
            "evidence_level": "A",
            "source_ref": "spec.pdf#page=20",
            "features_json": '{"node_type":"unit"}',
            "updated_at": now,
        },
        {
            "id": "9660:P2.7",
            "code": "P2.7",
            "title": "Integration",
            "unit_code": "P2",
            "strand": "Pure",
            "parent_id": "9660:P2",
            "difficulty_score": 0.7,
            "difficulty_label": "hard",
            "difficulty_confidence": 0.3,
            "evidence_level": "D",
            "source_ref": "spec.pdf#page=22",
            "features_json": '{"node_type":"topic"}',
            "updated_at": now,
        },
        {
            "id": "9660:P2.7.O01",
            "code": "P2.7.O01",
            "title": "Integration by parts",
            "unit_code": "P2",
            "strand": "Pure",
            "parent_id": "9660:P2.7",
            "difficulty_score": 0.76,
            "difficulty_label": "hard",
            "difficulty_confidence": 0.3,
            "evidence_level": "D",
            "source_ref": "spec.pdf#page=22",
            "features_json": (
                '{"node_type":"learning_objective",'
                '"description":"Use the reverse of the product rule.",'
                '"difficulty_method":"model-evidence-direct-v1",'
                '"cognitive_demand":0.72}'
            ),
            "updated_at": now,
        },
        {
            "id": "9660:P1.1.O01",
            "code": "P1.1.O01",
            "title": "Prior-unit objective",
            "unit_code": "P1",
            "strand": "Pure",
            "parent_id": "9660:ROOT",
            "difficulty_score": 0.5,
            "difficulty_label": "medium",
            "difficulty_confidence": 0.3,
            "evidence_level": "D",
            "source_ref": "spec.pdf#page=10",
            "features_json": (
                '{"node_type":"learning_objective",'
                '"description":"Knowledge assessed synoptically in a later paper."}'
            ),
            "updated_at": now,
        },
    ]
    with sessions.begin() as session:
        session.add(
            SourceDocumentModel(
                id="spec-1",
                subject_code="9660",
                path="spec.pdf",
                filename="spec.pdf",
                source_type="syllabus",
                authority_tier="official",
                checksum="hash",
                status="converted",
                markdown_path="spec.md",
            )
        )
        session.add_all([KnowledgePointModel(subject_code="9660", **point) for point in points])
        session.add(
            KnowledgeRelationModel(
                id=1,
                source_id="9660:P2.7",
                target_id="9660:P2.7.O01",
                relation_type="contains",
                confidence=1.0,
                source_ref="spec.pdf#page=22",
            )
        )
        session.add(
            KnowledgeEvidenceModel(
                id=1,
                knowledge_point_id="9660:P2.7.O01",
                source_document_id="spec-1",
                page=22,
                section="Integration by parts",
                section_path_json='["Pure Mathematics 2","Integration"]',
                evidence_role="definition",
                excerpt="Integration by parts is the reverse of the product rule.",
                content_hash="definition-hash",
                confidence=1.0,
                source_ref="spec.pdf#page=22",
                created_at=now,
            )
        )
    return KnowledgeRepository(sessions)


def test_retrieval_cards_group_evidence_under_real_learning_objective() -> None:
    repository = make_knowledge_repository()
    points = list_knowledge_points(repository, subject_code="9660", unit_code="P2")
    objective = next(point for point in points if point["code"] == "P2.7.O01")

    assert objective["breadcrumb"] == (
        "Mathematics 9660 › Pure Mathematics 2 › Integration › Integration by parts"
    )
    assert objective["difficulty"]["method"] == "model-evidence-direct-v1"
    assert objective["references"][0]["section"] == "Integration by parts"

    textbook = {
        "excerpt": "Worked example: use integration by parts for this integral.",
        "score": 0.91,
        "metadata": {
            "document_id": "book-1",
            "source": "book.md",
            "source_type": "textbook",
            "authority_tier": "licensed_core",
            "page": None,
            "section": "Worked example 3",
            "section_path": ["Integration", "Worked example 3"],
            "knowledge_codes": ["P2.7.O01"],
        },
    }
    assessment = {
        "excerpt": "Evaluate the integral using integration by parts.",
        "score": 0.82,
        "metadata": {
            "document_id": "qp-1",
            "source": "paper.pdf",
            "source_type": "question_paper",
            "authority_tier": "official",
            "page": 5,
            "section": "Question 4",
            "knowledge_codes": ["P2.7.O01"],
        },
    }
    cards = build_retrieval_cards(
        repository,
        "Use P2.7.O01 to solve the integral.",
        [textbook, dict(textbook), assessment],
        subject_code="9660",
        unit_code="P2",
        limit=3,
    )

    assert [card["code"] for card in cards] == ["P2.7.O01"]
    roles = [reference["evidence_role"] for reference in cards[0]["references"]]
    assert roles == ["definition", "assessment"]


def test_retrieval_cards_do_not_publish_lexical_only_catalog_matches() -> None:
    repository = make_knowledge_repository()

    cards = build_retrieval_cards(
        repository,
        "Explain integration by parts.",
        [],
        subject_code="9660",
        unit_code="P2",
        limit=3,
    )

    assert cards == []


def test_retrieval_cards_resolve_explicit_cross_unit_evidence_link() -> None:
    repository = make_knowledge_repository()

    cards = build_retrieval_cards(
        repository,
        "Apply prior-unit knowledge in this synoptic question.",
        [
            {
                "excerpt": "Knowledge assessed synoptically in a later paper.",
                "score": 0.94,
                "metadata": {
                    "document_id": "book-1",
                    "source": "book.md",
                    "source_type": "textbook",
                    "authority_tier": "licensed_core",
                    "knowledge_codes": ["P1.1.O01"],
                },
            }
        ],
        subject_code="9660",
        unit_code="P2",
        limit=3,
    )

    assert [card["code"] for card in cards] == ["P1.1.O01"]


def test_direct_catalog_scores_favor_question_match_without_exceeding_one() -> None:
    repository = make_knowledge_repository()

    cards = build_retrieval_cards(
        repository,
        "Explain integration by parts as the reverse of the product rule.",
        [
            {
                "excerpt": "Prior-unit objective",
                "score": 0.99,
                "metadata": {
                    "node_kind": "evidence_chunk",
                    "knowledge_code": "P1.1.O01",
                    "knowledge_codes": ["P1.1.O01"],
                    "knowledge_match_confidence": {"P1.1.O01": 0.3},
                },
            },
            {
                "excerpt": "Integration by parts",
                # Sparse Qdrant scores are not normalized and may exceed one.
                "score": 2.5,
                "metadata": {
                    "node_kind": "knowledge_point",
                    "knowledge_code": "P2.7.O01",
                    "knowledge_codes": ["P2.7.O01"],
                    "catalog_sparse_rank": 1,
                },
            },
        ],
        subject_code="9660",
        unit_code="P2",
        limit=2,
    )

    assert [card["code"] for card in cards] == ["P2.7.O01", "P1.1.O01"]
    assert all(0 <= card["retrieval_score"] <= 1 for card in cards)


def test_direct_catalog_question_match_outweighs_incidental_sparse_rank() -> None:
    repository = make_knowledge_repository()

    cards = build_retrieval_cards(
        repository,
        "Explain integration by parts as the reverse of the product rule.",
        [
            {
                "excerpt": "Surds",
                "score": 3.0,
                "metadata": {
                    "node_kind": "knowledge_point",
                    "knowledge_code": "P1.1.O01",
                    "catalog_sparse_rank": 1,
                },
            },
            {
                "excerpt": "Integration by parts",
                "score": 0.2,
                "metadata": {
                    "node_kind": "knowledge_point",
                    "knowledge_code": "P2.7.O01",
                    "catalog_sparse_rank": 3,
                },
            },
        ],
        subject_code="9660",
        unit_code="P2",
        limit=2,
    )

    assert [card["code"] for card in cards] == ["P2.7.O01", "P1.1.O01"]


def test_graph_transformation_query_matches_official_inflected_title() -> None:
    matches = match_knowledge_points(
        "Transform the graph of y = inverse sine x into y = one half inverse sine of x plus one.",
        [
            {
                "code": "P2.1.O05",
                "title": "Combinations of the transformations on the graph of y = f(x).",
                "definition": "Use combinations of transformations on graphs of functions.",
                "features": {"node_type": "learning_objective"},
            },
            {
                "code": "P2.4.O01",
                "title": "Knowledge of inverse sine functions and their domains and graphs.",
                "definition": "Understand the principal inverse trigonometric functions.",
                "features": {"node_type": "learning_objective"},
            },
        ],
        limit=2,
    )

    assert [point["code"] for _, point in matches] == ["P2.1.O05", "P2.4.O01"]
    assert matches[0][0] == 0.92
