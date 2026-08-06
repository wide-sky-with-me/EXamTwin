from examtwin.knowledge.retrieval_evaluation import (
    RetrievalCase,
    RetrievalEvaluationDataset,
    RetrievalTarget,
    evaluate_retrieval,
)
from llama_index.core.schema import NodeWithScore, TextNode


def _node(code: str, *, unit_code: str = "P1") -> NodeWithScore:
    return NodeWithScore(
        node=TextNode(
            text=code,
            metadata={
                "subject_code": "9660",
                "unit_code": unit_code,
                "knowledge_code": code,
                "source_type": "syllabus",
            },
        ),
        score=1.0,
    )


def test_retrieval_evaluation_measures_rank_and_filter_integrity() -> None:
    dataset = RetrievalEvaluationDataset(
        subject_code="9660",
        top_k=3,
        minimum_recall_at_k=1,
        minimum_mrr=0.5,
        cases=[
            RetrievalCase(
                id="surds",
                query="rationalise a surd denominator",
                unit_code="P1",
                targets=[RetrievalTarget(knowledge_code="P1.1.O01")],
            )
        ],
    )

    def retrieve(_query: str, **_kwargs) -> list[NodeWithScore]:
        return [_node("P1.2.O01"), _node("P1.1.O01")]

    report = evaluate_retrieval(dataset, retrieve)

    assert report["recall_at_k"] == 1
    assert report["mrr"] == 0.5
    assert report["scope_violations"] == 0
    assert report["passed"] is True
