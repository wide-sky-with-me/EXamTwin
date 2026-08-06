from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

import pytest
from examtwin.assessment.paper_classification import (
    PaperDocumentClassification,
    PaperDocumentClassifier,
    require_question_paper,
)
from examtwin.platform.agent_runtime.model import HarnessMessage
from examtwin.platform.config import Settings
from pydantic import BaseModel

StructuredResultT = TypeVar("StructuredResultT", bound=BaseModel)


class StubStructuredModel:
    model_name = "document-classifier-test"

    def __init__(self, result: PaperDocumentClassification) -> None:
        self.result = result
        self.messages: Sequence[HarnessMessage] = ()

    def complete(
        self,
        messages: Sequence[HarnessMessage],
        response_model: type[StructuredResultT],
        *,
        timeout: float,
    ) -> StructuredResultT:
        assert response_model is PaperDocumentClassification
        assert timeout > 0
        self.messages = messages
        return response_model.model_validate(self.result.model_dump(mode="json"))


def classification(document_type: str, confidence: float = 0.98) -> PaperDocumentClassification:
    return PaperDocumentClassification.model_validate(
        {
            "document_type": document_type,
            "confidence": confidence,
            "evidence": ["exact document evidence"],
            "rationale": "The dominant document purpose determines the classification.",
        }
    )


def test_classifier_sends_actual_content_to_the_structured_model() -> None:
    model = StubStructuredModel(classification("mark_scheme"))
    classifier = PaperDocumentClassifier(Settings(), structured_model=model)

    result = classifier.classify(
        "Scoring guidance and acceptable answers for every question in the examination."
    )

    assert result.document_type == "mark_scheme"
    assert model.messages[0].role == "system"
    assert "never infer its type from a filename" in model.messages[0].content
    assert "Scoring guidance and acceptable answers" in model.messages[1].content


@pytest.mark.parametrize(
    "document_type",
    [
        "mark_scheme",
        "source_booklet",
        "answer_booklet",
        "examiner_report",
        "specification",
        "teaching_material",
        "other",
    ],
)
def test_non_question_content_is_never_allowed_to_reach_question_splitting(
    document_type: str,
) -> None:
    with pytest.raises(ValueError, match="请选择完整的 Question Paper"):
        require_question_paper(classification(document_type))


def test_low_confidence_question_paper_is_stopped_as_ambiguous() -> None:
    with pytest.raises(ValueError, match="置信度不足"):
        require_question_paper(classification("question_paper", confidence=0.6))


def test_high_confidence_question_paper_passes_the_gate() -> None:
    require_question_paper(classification("question_paper", confidence=0.95))
