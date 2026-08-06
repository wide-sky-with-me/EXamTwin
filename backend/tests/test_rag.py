import json

from examtwin.answering_agent.contracts import (
    AnswerAgentResult,
    AnswerTask,
    QuestionImage,
)
from examtwin.config import Settings
from examtwin.schemas import AskRequest, Citation
from examtwin.services.model_json import parse_json_response
from examtwin.services.rag import (
    RagService,
    _card_node,
    calibrate_evidence_confidence,
    relevant_node_excerpt,
)
from examtwin.services.subject_context import subject_context
from llama_index.core.schema import NodeWithScore, TextNode


def test_parse_json_response_preserves_latex_backslashes() -> None:
    response = r"""
    ```json
    {
      "questions": [
        {
          "number": "1",
          "question_markdown": "Solve \\(x^2=4\\) using \frac{x}{2}; then state x \neq 0."
        }
      ]
    }
    ```
    """

    question = parse_json_response(response)["questions"][0]["question_markdown"]

    assert question == r"Solve \(x^2=4\) using \frac{x}{2}; then state x \neq 0."


def test_parse_json_response_keeps_valid_json_escapes() -> None:
    expected = {
        "answer": "first line\nsecond line",
        "quote": 'say "hello"',
        "display": "\\[\nu_n=1\n\\]",
    }
    response = json.dumps(expected)

    assert parse_json_response(response) == expected


def test_unmapped_or_unlocatable_chunks_cannot_claim_full_grounding() -> None:
    confidence, grounded, warnings = calibrate_evidence_confidence(
        [
            Citation(
                source="random-chunk.md",
                source_type="textbook",
                authority_tier="supplementary",
                excerpt="A fragment without a section or knowledge-point identity.",
            )
        ],
        claimed_confidence=1.0,
        claimed_grounded=True,
    )

    assert confidence == 0.55
    assert grounded is False
    assert any("普通文本片段" in warning for warning in warnings)
    assert any("页码或章节" in warning for warning in warnings)


def test_cold_start_card_without_mark_scheme_has_explainable_confidence_cap() -> None:
    confidence, grounded, warnings = calibrate_evidence_confidence(
        [
            Citation(
                source="spec.pdf",
                document_id="spec-1",
                page=22,
                source_type="syllabus",
                authority_tier="official",
                knowledge_code="P2.7.O01",
                evidence_role="definition",
                content_url="/sources/spec-1/context?page=22",
                excerpt="Integration by parts.",
            )
        ],
        claimed_confidence=1.0,
        claimed_grounded=True,
        knowledge_evidence_levels=["D"],
        mark_scheme_expected=True,
    )

    assert confidence == 0.82
    assert grounded is True
    assert any("D 级冷启动" in warning for warning in warnings)
    assert any("mark scheme" in warning for warning in warnings)


def test_atomic_table_citation_uses_query_relevant_rows() -> None:
    table = (
        "<table><tr><td>Question</td><td>Mark scheme</td></tr>"
        + "".join(
            f"<tr><td>{index}</td><td>Unrelated algebra row {index}</td></tr>"
            for index in range(80)
        )
        + (
            "<tr><td>81</td><td>Use a binomial hypothesis test and identify "
            "the critical region.</td></tr></table>"
        )
    )
    node = NodeWithScore(
        node=TextNode(
            text=table,
            metadata={
                "block_kind": "table",
                "retrieval_text": "bounded projection",
            },
        ),
        score=0.9,
    )
    original_content = node.node.get_content()

    excerpt = relevant_node_excerpt(
        node,
        "binomial hypothesis test critical region",
    )

    assert "Question" in excerpt
    assert "binomial hypothesis test" in excerpt
    assert "Unrelated algebra row" not in excerpt
    assert excerpt.endswith("</table>")
    assert node.node.get_content() == original_content == table


def test_knowledge_card_preserves_subject_and_unit_scope() -> None:
    node = _card_node(
        {
            "id": "9660:P1.1.O01",
            "code": "P1.1.O01",
            "title": "Use and manipulation of surds.",
            "definition": "Simplify surds and rationalise denominators.",
            "breadcrumb": "Mathematics › P1 › Surds",
            "subject_code": "9660",
            "unit_code": "P1",
            "source_ref": "spec.pdf",
            "path": [],
            "relations": [],
            "references": [],
            "retrieval_score": 0.9,
            "difficulty": {
                "score": 0.3,
                "label": "easy",
                "confidence": 0.4,
                "evidence_level": "D",
                "rationale": "Cold-start estimate.",
            },
        }
    )

    assert node.node.metadata["subject_code"] == "9660"
    assert node.node.metadata["unit_code"] == "P1"


def test_rag_unit_scope_accepts_global_but_not_other_unit_evidence() -> None:
    def node(unit_code: str) -> NodeWithScore:
        return NodeWithScore(
            node=TextNode(
                text="Approved subject evidence.",
                metadata={
                    "subject_code": "9660",
                    "unit_code": unit_code,
                    "source_type": "textbook",
                    "authority_tier": "licensed_core",
                    "source_role": "core_knowledge",
                },
            )
        )

    scope = {
        "subject_code": "9660",
        "unit_code": "P1",
        "pair_key": None,
        "source_types": set(),
        "authority_tiers": {"licensed_core"},
    }

    assert RagService._in_scope(node(""), **scope)
    assert RagService._in_scope(node("P1"), **scope)
    assert not RagService._in_scope(node("P2"), **scope)


def test_rag_carries_question_images_into_answer_task(monkeypatch) -> None:
    captured: list[AnswerTask] = []

    class CapturingRuntime:
        def solve(self, task: AnswerTask, **_kwargs) -> AnswerAgentResult:
            captured.append(task)
            return AnswerAgentResult(
                answer_markdown="Candidate answer.",
                citations=(),
                diagrams=(),
                confidence=0.5,
                grounded=False,
                warnings=(),
                steps=(),
            )

    monkeypatch.setattr(
        "examtwin.services.rag.build_answering_runtime",
        lambda *_args, **_kwargs: CapturingRuntime(),
    )
    image = QuestionImage(page_number=4, content=b"\xff\xd8page-4")

    RagService(Settings(), subject_context(Settings()), final_answer_provider=object()).ask(
        AskRequest(subject_code="9660", question="Read the original graph."),
        question_images=(image,),
    )

    assert captured[0].question_images == (image,)
