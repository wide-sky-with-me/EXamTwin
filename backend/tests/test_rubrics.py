from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeVar, cast

from examtwin.agent_harness import HarnessMessage
from examtwin.config import Settings
from examtwin.persistence.models import RubricCriterionModel, RubricSetModel
from examtwin.persistence.rubric_repository import RubricRepository
from examtwin.services.rubrics import RubricService
from examtwin.services.subject_context import subject_context
from pydantic import BaseModel

StructuredResultT = TypeVar("StructuredResultT", bound=BaseModel)


class RubricModelWithPrintedQuestionLabels:
    model_name = "fake-rubric-model"

    def complete(
        self,
        messages: Sequence[HarnessMessage],
        response_model: type[StructuredResultT],
        *,
        timeout: float,
    ) -> StructuredResultT:
        assert timeout > 0
        assert messages
        return response_model.model_validate(
            {
                "criteria": [
                    {
                        "question_number": "Q1",
                        "subpart": "whole",
                        "criterion_id": "01-B1",
                        "scoring_mode": "point_based",
                        "mark_type": "B1",
                        "max_marks": 1,
                        "description": "Select option B.",
                        "source_excerpt": "Answer: B",
                        "confidence": 1,
                    },
                    {
                        "question_number": "16.1",
                        "subpart": "whole",
                        "criterion_id": "16.1-B3",
                        "scoring_mode": "point_based",
                        "mark_type": "B3",
                        "max_marks": 3,
                        "description": "Give a precise definition.",
                        "source_excerpt": "A full and precise definition is given (3 marks)",
                        "confidence": 1,
                    },
                ],
                "warnings": [],
            }
        )


class PaperRecords:
    def get(self, _paper_job_id: str) -> dict[str, object]:
        return {
            "subject_code": "9640",
            "filename": "A-Level-AQA经济学-国际卷QP-202406-Economics-U1-AQA.pdf",
            "status": "completed",
        }

    def questions(self, _paper_job_id: str) -> list[dict[str, object]]:
        return [
            {"number": "01", "question_markdown": "Choose the normative statement."},
            {"number": "16", "question_markdown": "Define income elasticity of demand."},
        ]


class MarkSchemeRecords:
    def get(self, _source_document_id: str) -> dict[str, object]:
        return {
            "id": "mark-scheme-1",
            "subject_code": "9640",
            "source_type": "mark_scheme",
            "pair_key": "9640:2024:JUN:U1",
            "filename": "A-Level-AQA经济学-国际卷MS-202406-Economics-U1-AQA.pdf",
            "markdown_path": "unused.md",
        }


class CapturingRubrics:
    def __init__(self) -> None:
        self.criteria: list[dict[str, object]] = []

    def create(self, **values: object) -> dict[str, object]:
        self.criteria = cast(list[dict[str, object]], values["criteria"])
        return {"id": "rubric-1", **values}


class RubricServiceWithMarkdown(RubricService):
    def _document_markdown(self, document: dict[str, object]) -> str:
        assert document
        return "Official mark scheme content"


class FlushOrderingSession:
    def __init__(self) -> None:
        self.set_added = False
        self.set_flushed = False

    def scalar(self, _statement: object) -> int:
        return 0

    def add(self, row: object) -> None:
        if isinstance(row, RubricSetModel):
            self.set_added = True
        elif isinstance(row, RubricCriterionModel):
            assert self.set_flushed, "rubric criteria cannot precede their persisted rubric set"

    def flush(self) -> None:
        assert self.set_added
        self.set_flushed = True


class FlushOrderingTransaction:
    def __init__(self, session: FlushOrderingSession) -> None:
        self.session = session

    def __enter__(self) -> FlushOrderingSession:
        return self.session

    def __exit__(self, *_args: object) -> None:
        return None


class FlushOrderingSessions:
    def __init__(self) -> None:
        self.session = FlushOrderingSession()

    def begin(self) -> FlushOrderingTransaction:
        return FlushOrderingTransaction(self.session)


class RubricRepositoryWithoutReadback(RubricRepository):
    def get(self, rubric_id: str) -> dict[str, Any]:
        return {"id": rubric_id}


def test_rubric_creation_maps_printed_subpart_labels_to_persisted_questions() -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingRubrics()
    service = RubricServiceWithMarkdown(
        settings,
        subject_context(settings),
        cast(Any, MarkSchemeRecords()),
        cast(Any, PaperRecords()),
        cast(Any, rubrics),
        cast(Any, None),
        cast(Any, None),
        structured_model=RubricModelWithPrintedQuestionLabels(),
    )

    service.create(paper_job_id="paper-1", source_document_id="mark-scheme-1")

    assert [criterion["question_number"] for criterion in rubrics.criteria] == ["01", "16"]
    assert [criterion["subpart"] for criterion in rubrics.criteria] == ["whole", "1"]


def test_rubric_repository_persists_set_before_its_criteria() -> None:
    sessions = FlushOrderingSessions()
    repository = RubricRepositoryWithoutReadback(cast(Any, sessions))

    repository.create(
        subject_id="subject-1",
        paper_job_id="paper-1",
        source_document_id="mark-scheme-1",
        identity={},
        parser_model="fake-rubric-model",
        warnings=[],
        criteria=[
            {
                "question_number": "01",
                "subpart": "whole",
                "criterion_id": "01-B1",
                "scoring_mode": "point_based",
                "mark_type": "B1",
                "max_marks": 1,
                "description": "Select option B.",
                "source_excerpt": "Answer: B",
                "confidence": 1,
            }
        ],
    )

    assert sessions.session.set_flushed is True
