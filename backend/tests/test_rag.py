import json

from examtwin.assessment.answering_agent.contracts import (
    AnswerAgentResult,
    AnswerTask,
    QuestionImage,
)
from examtwin.assessment.rag import (
    RagService,
    _card_node,
    calibrate_evidence_confidence,
    relevant_node_excerpt,
    rerank_retrieval_candidates,
    retain_direct_catalog_candidates,
)
from examtwin.contracts import AskRequest, Citation
from examtwin.platform.config import Settings
from examtwin.platform.model_json import parse_json_response
from examtwin.subjects.public import subject_context
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


def test_rag_unit_scope_accepts_global_and_cross_unit_catalog_but_not_other_unit_evidence() -> None:
    def node(unit_code: str, *, node_kind: str = "evidence_chunk") -> NodeWithScore:
        return NodeWithScore(
            node=TextNode(
                text="Approved subject evidence.",
                metadata={
                    "subject_code": "9660",
                    "unit_code": unit_code,
                    "source_type": "textbook",
                    "authority_tier": "licensed_core",
                    "source_role": "core_knowledge",
                    "node_kind": node_kind,
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
    assert RagService._in_scope(node("P2", node_kind="knowledge_point"), **scope)


def test_public_retrieve_keeps_cards_and_raw_fallbacks_inside_scope(monkeypatch) -> None:
    pair_key = "9660:2026:JAN:P1"

    def candidate(
        document_id: str,
        *,
        candidate_pair_key: str,
        source_type: str = "textbook",
        score: float,
    ) -> NodeWithScore:
        return NodeWithScore(
            node=TextNode(
                id_=document_id,
                text=f"Evidence from {document_id}",
                metadata={
                    "node_kind": "evidence_chunk",
                    "subject_code": "9660",
                    "unit_code": "P1",
                    "pair_key": candidate_pair_key,
                    "source_type": source_type,
                    "source_role": "core_knowledge",
                    "authority_tier": "licensed_core",
                    "document_id": document_id,
                    "page": 1,
                    "section": document_id,
                },
            ),
            score=score,
        )

    candidates = [
        candidate("mapped", candidate_pair_key=pair_key, score=0.9),
        candidate("raw", candidate_pair_key=pair_key, score=0.8),
        candidate("wrong-pair", candidate_pair_key="9660:2025:JUN:P1", score=1.0),
        candidate(
            "wrong-source",
            candidate_pair_key=pair_key,
            source_type="mark_scheme",
            score=1.0,
        ),
    ]
    captured: dict[str, list[str]] = {}

    class FakeVectorStore:
        enable_hybrid = False

    class FakeRetriever:
        def retrieve(self, _question: str) -> list[NodeWithScore]:
            return candidates

    class FakeIndex:
        vector_store = FakeVectorStore()

        def as_retriever(self, **_kwargs) -> FakeRetriever:
            return FakeRetriever()

    class CapturingReranker:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def rerank(
            self,
            _question: str,
            nodes: list[NodeWithScore],
            *,
            top_n: int,
        ) -> list[NodeWithScore]:
            del top_n
            captured["reranked"] = [node.node.node_id for node in nodes]
            return nodes

    def build_cards(
        _repository,
        _question: str,
        evidence_items: list[dict],
        **_kwargs,
    ) -> list[dict]:
        captured["cards"] = [str(item["metadata"]["document_id"]) for item in evidence_items]
        return [
            {
                "id": "9660:P1.1.O01",
                "code": "P1.1.O01",
                "title": "Approved objective",
                "definition": "Use approved evidence.",
                "breadcrumb": "Mathematics › P1",
                "subject_code": "9660",
                "unit_code": "P1",
                "source_ref": "mapped",
                "path": [],
                "relations": [],
                "references": [
                    {
                        "source": "mapped",
                        "document_id": "mapped",
                        "page": 1,
                        "section": "mapped",
                        "unit_code": "P1",
                        "source_type": "textbook",
                        "authority_tier": "licensed_core",
                        "pair_key": pair_key,
                        "excerpt": "Evidence from mapped",
                    }
                ],
                "retrieval_score": 0.9,
                "difficulty": {
                    "score": 0.3,
                    "label": "easy",
                    "confidence": 0.4,
                    "evidence_level": "D",
                    "rationale": "Cold-start estimate.",
                },
            }
        ]

    monkeypatch.setattr(
        "examtwin.assessment.rag.build_embedding",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        "examtwin.assessment.rag.load_vector_index",
        lambda *_args, **_kwargs: FakeIndex(),
    )
    monkeypatch.setattr(
        "examtwin.assessment.rag.SiliconFlowReranker",
        CapturingReranker,
    )
    monkeypatch.setattr(
        "examtwin.assessment.rag.build_retrieval_cards",
        build_cards,
    )

    settings = Settings(retrieval_raw_fallback_count=2)
    results = RagService(
        settings,
        subject_context(settings),
        knowledge_repository=object(),
        final_answer_provider=object(),
    ).retrieve(
        "approved evidence",
        subject_code="9660",
        unit_code="P1",
        pair_key=pair_key,
        source_types=["textbook"],
        authority_tiers=["licensed_core"],
        top_k=4,
    )

    assert captured == {
        "reranked": ["mapped", "raw"],
        "cards": ["mapped", "raw"],
    }
    assert [node.node.metadata["document_id"] for node in results] == [
        "mapped",
        "raw",
    ]


def test_reranker_cannot_drop_direct_catalog_candidates() -> None:
    def node(node_id: str, *, node_kind: str) -> NodeWithScore:
        return NodeWithScore(
            node=TextNode(
                id_=node_id,
                text=node_id,
                metadata={"node_kind": node_kind},
            ),
            score=0.8,
        )

    evidence = node("evidence", node_kind="evidence_chunk")
    catalog = node("catalog", node_kind="knowledge_point")
    dropped_evidence = node("dropped", node_kind="evidence_chunk")

    retained = retain_direct_catalog_candidates(
        [evidence],
        [evidence, catalog, dropped_evidence],
    )

    assert [item.node.node_id for item in retained] == ["evidence", "catalog"]


def test_retrieval_reranks_only_source_evidence_and_retains_direct_catalog() -> None:
    def node(node_id: str, *, node_kind: str, score: float) -> NodeWithScore:
        return NodeWithScore(
            node=TextNode(
                id_=node_id,
                text=node_id,
                metadata={"node_kind": node_kind},
            ),
            score=score,
        )

    evidence = node("evidence", node_kind="evidence_chunk", score=0.7)
    catalog = node("catalog", node_kind="knowledge_point", score=0.9)
    received: list[str] = []

    def rerank(_question: str, candidates: list[NodeWithScore], *, top_n: int):
        received.extend(item.node.node_id for item in candidates)
        assert top_n == 1
        return candidates

    reranked, fallback = rerank_retrieval_candidates(
        "query",
        [evidence, catalog],
        top_n=1,
        rerank=rerank,
    )

    assert received == ["evidence"]
    assert [item.node.node_id for item in reranked] == ["evidence", "catalog"]
    assert fallback is False


def test_retrieval_falls_back_to_hybrid_scores_when_reranker_times_out() -> None:
    def node(node_id: str, score: float) -> NodeWithScore:
        return NodeWithScore(
            node=TextNode(
                id_=node_id,
                text=node_id,
                metadata={"node_kind": "evidence_chunk"},
            ),
            score=score,
        )

    def timeout(*_args, **_kwargs):
        raise TimeoutError("reranker timed out")

    reranked, fallback = rerank_retrieval_candidates(
        "query",
        [node("weaker", 0.4), node("stronger", 0.9)],
        top_n=1,
        rerank=timeout,
    )

    assert [item.node.node_id for item in reranked] == ["stronger", "weaker"]
    assert fallback is True


def test_query_provider_timeout_is_bounded_independently_from_index_timeout(
    monkeypatch,
) -> None:
    settings = Settings(
        embedding_timeout=120,
        rerank_timeout=30,
        retrieval_provider_timeout=15,
    )
    captured: dict[str, object] = {}

    class FakeEmbedding:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        "examtwin.platform.providers.ResilientOpenAIEmbedding",
        FakeEmbedding,
    )

    from examtwin.platform.providers import build_embedding

    build_embedding(settings, timeout=settings.retrieval_provider_timeout, max_retries=0)

    assert captured["timeout"] == 15
    assert captured["max_retries"] == 0


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
        "examtwin.assessment.rag.build_answering_runtime",
        lambda *_args, **_kwargs: CapturingRuntime(),
    )
    image = QuestionImage(page_number=4, content=b"\xff\xd8page-4")

    RagService(Settings(), subject_context(Settings()), final_answer_provider=object()).ask(
        AskRequest(subject_code="9660", question="Read the original graph."),
        question_images=(image,),
    )

    assert captured[0].question_images == (image,)
