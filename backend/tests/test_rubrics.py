from __future__ import annotations

import json
import re
import uuid
from collections.abc import Sequence
from pathlib import Path
from threading import Event, Thread
from typing import Any, TypeVar, cast

import pytest
from examtwin.assessment.assessment_repository import AssessmentRepository
from examtwin.assessment.rubric_repository import RubricConflictError, RubricRepository
from examtwin.assessment.rubrics import AiReviewModelError, RubricService
from examtwin.contracts.rubrics import (
    AiReviewRubricCriteriaRequest,
    BatchReviewRubricCriteriaRequest,
)
from examtwin.knowledge.corpus_ingestion import CorpusIngestor
from examtwin.platform.agent_runtime import HarnessMessage
from examtwin.platform.config import Settings, get_settings
from examtwin.platform.database.migrations import upgrade_database
from examtwin.platform.database.models import (
    PaperJobModel,
    RubricCriterionModel,
    RubricCriterionReviewModel,
    RubricSetModel,
    SourceDocumentModel,
    SubjectModel,
)
from examtwin.platform.database.session import create_session_factory, utcnow
from examtwin.subjects.public import subject_context
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


class SingleQuestionRubricModel:
    model_name = "single-question-rubric-model"

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.prompts: list[str] = []

    def complete(
        self,
        messages: Sequence[HarnessMessage],
        response_model: type[StructuredResultT],
        *,
        timeout: float,
    ) -> StructuredResultT:
        assert timeout > 0
        user_content = next(message.content for message in messages if message.role == "user")
        self.prompts.append(user_content)
        question_numbers = re.findall(r"(?m)^QUESTION ([^:]+):", user_content)
        if len(question_numbers) != 1:
            raise TimeoutError("combined rubric extraction exceeded its time budget")
        number = question_numbers[0]
        self.calls.append(number)
        return response_model.model_validate(
            {
                "criteria": [
                    {
                        "question_number": number,
                        "subpart": "whole",
                        "criterion_id": f"{number}-B1",
                        "scoring_mode": "point_based",
                        "mark_type": "B1",
                        "max_marks": 1,
                        "description": f"Award the mark for question {number}.",
                        "source_excerpt": f"Question {number}: B1",
                        "confidence": 1,
                    }
                ],
                "warnings": [],
            }
        )


class StaticRubricModel:
    model_name = "static-rubric-model"

    def __init__(
        self,
        criteria: list[dict[str, object]],
        *,
        warnings: list[str] | None = None,
    ) -> None:
        self.criteria = criteria
        self.warnings = warnings or []

    def complete(
        self,
        messages: Sequence[HarnessMessage],
        response_model: type[StructuredResultT],
        *,
        timeout: float,
    ) -> StructuredResultT:
        assert timeout > 0
        assert messages
        return response_model.model_validate({"criteria": self.criteria, "warnings": self.warnings})


class CorrectingBudgetRubricModel:
    model_name = "correcting-budget-rubric-model"

    def __init__(self, *, remains_invalid: bool = False) -> None:
        self.calls = 0
        self.prompts: list[str] = []
        self.remains_invalid = remains_invalid

    def complete(
        self,
        messages: Sequence[HarnessMessage],
        response_model: type[StructuredResultT],
        *,
        timeout: float,
    ) -> StructuredResultT:
        assert timeout > 0
        self.calls += 1
        user_content = next(message.content for message in messages if message.role == "user")
        self.prompts.append(user_content)
        criteria: list[dict[str, object]] = [
            {
                "question_number": "01",
                "subpart": "whole",
                "criterion_id": "01-B1",
                "scoring_mode": "point_based",
                "mark_type": "B1",
                "max_marks": 1,
                "description": "Select the correct option.",
                "source_excerpt": "Answer: B",
                "confidence": 1,
            }
        ]
        if self.calls == 1 or self.remains_invalid:
            criteria.append(
                {
                    "question_number": "01",
                    "subpart": "whole",
                    "criterion_id": "01-total-check",
                    "scoring_mode": "point_based",
                    "mark_type": None,
                    "max_marks": 0.03,
                    "description": "Question total check.",
                    "source_excerpt": "Question total: 1",
                    "confidence": 0.5,
                }
            )
        return response_model.model_validate({"criteria": criteria, "warnings": []})


class CorrectingControlCharacterRubricModel(CorrectingBudgetRubricModel):
    model_name = "correcting-control-character-rubric-model"

    def complete(
        self,
        messages: Sequence[HarnessMessage],
        response_model: type[StructuredResultT],
        *,
        timeout: float,
    ) -> StructuredResultT:
        assert timeout > 0
        self.calls += 1
        user_content = next(message.content for message in messages if message.role == "user")
        self.prompts.append(user_content)
        invalid_description = "The vector is \x00invalid."
        valid_description = r"The vector is \mathbf{v}."
        description = invalid_description if self.calls == 1 else valid_description
        return response_model.model_validate(
            {
                "criteria": [
                    {
                        "question_number": "01",
                        "subpart": "whole",
                        "criterion_id": "01-B1",
                        "scoring_mode": "point_based",
                        "mark_type": "B1",
                        "max_marks": 1,
                        "description": description,
                        "source_excerpt": "B1 for the correct vector",
                        "confidence": 1,
                    }
                ],
                "warnings": [],
            }
        )


class PaperRecords:
    def get(self, _paper_job_id: str) -> dict[str, object]:
        return {
            "subject_code": "9640",
            "filename": "A-Level-AQA经济学-国际卷QP-202406-Economics-U1-AQA.pdf",
            "pair_key": "9640:2024:JUN:U1",
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
            "checksum": "mark-scheme-checksum-v1",
            "converted_source_checksum": "mark-scheme-checksum-v1",
            "identity_status": "complete",
            "filename": "A-Level-AQA经济学-国际卷MS-202406-Economics-U1-AQA.pdf",
            "markdown_path": "unused.md",
        }


class PaperRecordsWithoutStoredPair(PaperRecords):
    def get(self, paper_job_id: str) -> dict[str, object]:
        row = super().get(paper_job_id)
        row.pop("pair_key")
        return row


class PaperRecordsWithoutIdentity(PaperRecordsWithoutStoredPair):
    def get(self, paper_job_id: str) -> dict[str, object]:
        row = super().get(paper_job_id)
        row["filename"] = "paper.pdf"
        return row


class MarkSchemeRecordsWithoutIdentity(MarkSchemeRecords):
    def get(self, source_document_id: str) -> dict[str, object]:
        row = super().get(source_document_id)
        row["pair_key"] = None
        row["identity_status"] = "incomplete"
        return row


class MarkSchemeRecordsWithConflict(MarkSchemeRecords):
    def get(self, source_document_id: str) -> dict[str, object]:
        row = super().get(source_document_id)
        row["pair_key"] = "9640:2023:JUN:U1"
        return row


class MarkSchemeRecordsWithStaleConversion(MarkSchemeRecords):
    def get(self, source_document_id: str) -> dict[str, object]:
        row = super().get(source_document_id)
        row["converted_source_checksum"] = "mark-scheme-checksum-v0"
        return row


class CapturingRubrics:
    def __init__(self) -> None:
        self.criteria: list[dict[str, object]] = []

    def create(self, **values: object) -> dict[str, object]:
        self.criteria = cast(list[dict[str, object]], values["criteria"])
        return {"id": "rubric-1", **values}


class RubricServiceWithMarkdown(RubricService):
    def _document_markdown(
        self,
        document: dict[str, object],
        *,
        expected_checksum: str,
    ) -> str:
        self._require_converted_source(document, expected_checksum)
        self.markdown_reads = getattr(self, "markdown_reads", 0) + 1
        assert document
        return "Official mark scheme content"


class RubricServiceWithSourceMarkdown(RubricServiceWithMarkdown):
    def __init__(self, *args: object, source_markdown: str, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.source_markdown = source_markdown

    def _document_markdown(
        self,
        document: dict[str, object],
        *,
        expected_checksum: str,
    ) -> str:
        super()._document_markdown(document, expected_checksum=expected_checksum)
        return self.source_markdown


class SingleQuestionPaperRecords(PaperRecords):
    def questions(self, paper_job_id: str) -> list[dict[str, object]]:
        return super().questions(paper_job_id)[:1]


class SingleQuestionPaperRecordsWithBudget(SingleQuestionPaperRecords):
    def questions(self, paper_job_id: str) -> list[dict[str, object]]:
        questions = super().questions(paper_job_id)
        questions[0]["requirements_json"] = '{"total_marks": 1}'
        return questions


class MutableMarkSchemeRecords(MarkSchemeRecords):
    def __init__(self, source: Path) -> None:
        self.document = super().get("mark-scheme-1")
        self.document["path"] = str(source)

    def get(self, source_document_id: str) -> dict[str, object]:
        assert source_document_id == "mark-scheme-1"
        return dict(self.document)

    def update_status(self, document_id: str, status: str, **values: object) -> None:
        assert document_id == "mark-scheme-1"
        self.document.update(values)
        self.document["status"] = status

    def replace_source(self, checksum: str) -> None:
        self.document["checksum"] = checksum
        self.document["status"] = "discovered"
        self.document["markdown_path"] = None


class PausingRubricService(RubricService):
    def __init__(
        self,
        *args: object,
        read_ready: Event,
        resume_read: Event,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.read_ready = read_ready
        self.resume_read = resume_read

    def _document_markdown(
        self,
        document: dict[str, object],
        *,
        expected_checksum: str,
    ) -> str:
        self.read_ready.set()
        if not self.resume_read.wait(timeout=5):
            raise TimeoutError("Timed out waiting to resume the Markdown read")
        return super()._document_markdown(
            document,
            expected_checksum=expected_checksum,
        )


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
    def get(self, rubric_id: str, *, subject_id: str) -> dict[str, Any]:
        return {"id": rubric_id, "subject_id": subject_id}


def test_rubric_creation_maps_printed_subpart_labels_to_persisted_questions() -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingRubrics()
    service = RubricServiceWithMarkdown(
        settings,
        subject_context(settings),
        cast(Any, MarkSchemeRecords()),
        cast(Any, PaperRecordsWithoutStoredPair()),
        cast(Any, rubrics),
        cast(Any, None),
        cast(Any, None),
        structured_model=RubricModelWithPrintedQuestionLabels(),
    )

    created = service.create(paper_job_id="paper-1", source_document_id="mark-scheme-1")
    assert rubrics.criteria
    assert created["source_document_checksum"] == "mark-scheme-checksum-v1"

    assert [criterion["question_number"] for criterion in rubrics.criteria] == ["01", "16"]
    assert [criterion["subpart"] for criterion in rubrics.criteria] == ["whole", "1"]


def test_rubric_creation_normalizes_repeated_question_prefix_and_mark_type() -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingRubrics()
    model = StaticRubricModel(
        [
            {
                "question_number": "01",
                "subpart": "01(a)(i)",
                "criterion_id": "01a-M1",
                "scoring_mode": "point_based",
                "mark_type": "M",
                "max_marks": 1,
                "description": "Uses a valid method.",
                "source_excerpt": "M1 for a valid method",
                "confidence": 1,
            },
            {
                "question_number": "01",
                "subpart": "01(a)(i)",
                "criterion_id": "01a-B1ft",
                "scoring_mode": "point_based",
                "mark_type": "Bft",
                "max_marks": 1,
                "description": "Obtains the follow-through result.",
                "source_excerpt": "B1ft for the result",
                "confidence": 1,
            },
            {
                "question_number": "01(a)(ii)",
                "subpart": "whole",
                "criterion_id": "01a-A1",
                "scoring_mode": "point_based",
                "mark_type": "A",
                "max_marks": 1,
                "description": "Obtains the independently awarded result.",
                "source_excerpt": "A1 for the result",
                "confidence": 1,
            },
        ]
    )
    service = RubricServiceWithMarkdown(
        settings,
        subject_context(settings),
        cast(Any, MarkSchemeRecords()),
        cast(Any, SingleQuestionPaperRecords()),
        cast(Any, rubrics),
        cast(Any, None),
        cast(Any, None),
        structured_model=model,
    )

    service.create(paper_job_id="paper-1", source_document_id="mark-scheme-1")

    assert [criterion["question_number"] for criterion in rubrics.criteria] == [
        "01",
        "01",
        "01",
    ]
    assert [criterion["subpart"] for criterion in rubrics.criteria] == [
        "(a)(i)",
        "(a)(i)",
        "(a)(ii)",
    ]
    assert [criterion["mark_type"] for criterion in rubrics.criteria] == [
        "M1",
        "B1ft",
        "A1",
    ]


def test_rubric_creation_rejects_duplicate_scoring_atoms() -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingRubrics()
    shared = {
        "question_number": "01",
        "subpart": "(a)",
        "scoring_mode": "point_based",
        "mark_type": "B1",
        "max_marks": 1,
        "description": "States the required answer.",
        "source_excerpt": "Required answer",
        "confidence": 1,
    }
    service = RubricServiceWithMarkdown(
        settings,
        subject_context(settings),
        cast(Any, MarkSchemeRecords()),
        cast(Any, SingleQuestionPaperRecords()),
        cast(Any, rubrics),
        cast(Any, None),
        cast(Any, None),
        structured_model=StaticRubricModel(
            [
                {**shared, "criterion_id": "01a-B1-first"},
                {**shared, "criterion_id": "01a-B1-second"},
            ]
        ),
    )

    with pytest.raises(ValueError, match="包含重复评分原子"):
        service.create(paper_job_id="paper-1", source_document_id="mark-scheme-1")

    assert rubrics.criteria == []


def test_rubric_creation_rejects_mark_budget_mismatch() -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingRubrics()
    source_markdown = (
        "<table><tr><td>Q</td><td>Answer</td><td>Marks</td><td>Comments</td></tr>"
        "<tr><td>01(a)</td><td>Answer</td><td>M1A1</td><td></td></tr></table>"
    )
    service = RubricServiceWithSourceMarkdown(
        settings,
        subject_context(settings),
        cast(Any, MarkSchemeRecords()),
        cast(Any, SingleQuestionPaperRecords()),
        cast(Any, rubrics),
        cast(Any, None),
        cast(Any, None),
        structured_model=StaticRubricModel(
            [
                {
                    "question_number": "01",
                    "subpart": "(a)",
                    "criterion_id": "01a-M1",
                    "scoring_mode": "point_based",
                    "mark_type": "M1",
                    "max_marks": 1,
                    "description": "Uses a valid method.",
                    "source_excerpt": "M1 for a valid method",
                    "confidence": 1,
                }
            ]
        ),
        source_markdown=source_markdown,
    )

    with pytest.raises(ValueError, match="与 Mark Scheme 分值不一致"):
        service.create(paper_job_id="paper-1", source_document_id="mark-scheme-1")

    assert rubrics.criteria == []


def test_rubric_creation_retries_against_question_paper_mark_budget() -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingRubrics()
    model = CorrectingBudgetRubricModel()
    service = RubricServiceWithMarkdown(
        settings,
        subject_context(settings),
        cast(Any, MarkSchemeRecords()),
        cast(Any, SingleQuestionPaperRecordsWithBudget()),
        cast(Any, rubrics),
        cast(Any, None),
        cast(Any, None),
        structured_model=model,
    )

    service.create(paper_job_id="paper-1", source_document_id="mark-scheme-1")

    assert model.calls == 2
    assert "MARK BUDGET FOR TARGET QUESTION:\n1.0" in model.prompts[0]
    assert "CORRECTION REQUIRED" in model.prompts[1]
    assert [item["criterion_id"] for item in rubrics.criteria] == ["01-B1"]


def test_rubric_creation_rejects_persistent_question_paper_budget_mismatch() -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingRubrics()
    model = CorrectingBudgetRubricModel(remains_invalid=True)
    service = RubricServiceWithMarkdown(
        settings,
        subject_context(settings),
        cast(Any, MarkSchemeRecords()),
        cast(Any, SingleQuestionPaperRecordsWithBudget()),
        cast(Any, rubrics),
        cast(Any, None),
        cast(Any, None),
        structured_model=model,
    )

    with pytest.raises(ValueError, match="评分原子校验失败"):
        service.create(paper_job_id="paper-1", source_document_id="mark-scheme-1")

    assert model.calls == 3
    assert rubrics.criteria == []


def test_holistic_best_fit_descriptors_are_one_non_additive_criterion() -> None:
    from examtwin.assessment.rubrics import (
        RubricExtractionDraft,
        _collapse_holistic_best_fit_criteria,
    )

    mark_scheme = (
        "<table><tr><td>20</td><td>Analyse the issue.</td><td>12</td></tr>"
        "<tr><td></td><td>AO1, AO2 and AO3 are regarded as interdependent. "
        "Examiners use the best-fit approach. Level 3: 9-12 marks.</td><td></td>"
        "</tr></table>"
    )
    payload = RubricExtractionDraft.model_validate(
        {
            "criteria": [
                {
                    "question_number": "20",
                    "subpart": "whole",
                    "criterion_id": f"20-AO1-{index}",
                    "scoring_mode": "point_based",
                    "mark_type": "AO1",
                    "max_marks": 1,
                    "description": "Shows knowledge and analysis.",
                    "source_excerpt": "Level 3 descriptor.",
                    "confidence": 0.9,
                }
                for index in range(1, 4)
            ],
        }
    )

    collapsed = _collapse_holistic_best_fit_criteria(
        payload,
        mark_scheme,
        question={"number": "20", "total_marks": 12},
        settings=Settings(),
    )

    assert len(collapsed.criteria) == 1
    assert collapsed.criteria[0].scoring_mode == "levels_based"
    assert collapsed.criteria[0].max_marks == 12
    assert collapsed.criteria[0].description == "Shows knowledge and analysis."
    assert "non-additive" in collapsed.warnings[0]


def test_mark_scheme_context_keeps_level_grid_after_question_table() -> None:
    from examtwin.assessment.rubrics import _mark_scheme_context

    source = (
        "<table><tr><td>20</td><td>Analyse.</td><td>12</td></tr></table>\n"
        "AO1, AO2 and AO3 are interdependent; use a best-fit approach.\n"
        "<table><tr><td>Level</td><td>Marks</td><td>Descriptor</td></tr>"
        "<tr><td>3</td><td>9-12</td><td>Sound analysis.</td></tr></table>\n"
        "<table><tr><td>21</td><td>Assess.</td><td>20</td></tr></table>"
    )

    context = _mark_scheme_context(source, "20", settings=Settings())

    assert "best-fit" in context
    assert "Sound analysis" in context
    assert "Assess." not in context


def test_rubric_mark_budget_counts_alternative_route_once() -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingRubrics()
    source_markdown = (
        "<table><tr><td>Q</td><td>Answer</td><td>Marks</td><td>Comments</td></tr>"
        "<tr><td>01(a)</td><td>Primary</td><td>M1A1</td><td></td></tr>"
        "<tr><td>01(a) ALT</td><td>Alternative</td><td>M1A1</td><td></td></tr></table>"
    )
    criteria = [
        {
            "question_number": "01",
            "subpart": "(a)",
            "criterion_id": criterion_id,
            "scoring_mode": "point_based",
            "mark_type": mark_type,
            "max_marks": 1,
            "description": description,
            "source_excerpt": description,
            "confidence": 1,
        }
        for criterion_id, mark_type, description in (
            ("01a-M1", "M1", "Uses either valid method."),
            ("01a-A1", "A1", "Obtains the correct result."),
        )
    ]
    service = RubricServiceWithSourceMarkdown(
        settings,
        subject_context(settings),
        cast(Any, MarkSchemeRecords()),
        cast(Any, SingleQuestionPaperRecords()),
        cast(Any, rubrics),
        cast(Any, None),
        cast(Any, None),
        structured_model=StaticRubricModel(criteria),
        source_markdown=source_markdown,
    )

    service.create(paper_job_id="paper-1", source_document_id="mark-scheme-1")

    assert len(rubrics.criteria) == 2


def test_rubric_creation_deduplicates_equivalent_source_page_warnings() -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingRubrics()
    criterion = {
        "question_number": "01",
        "subpart": "(a)",
        "criterion_id": "01a-B1",
        "scoring_mode": "point_based",
        "mark_type": "B1",
        "max_marks": 1,
        "description": "States the required answer.",
        "source_excerpt": "Required answer",
        "confidence": 1,
    }
    model = StaticRubricModel(
        [criterion],
        warnings=[
            "The official excerpt does not provide source page numbers.",
            "The source_page is null because the PDF page is not specified.",
            "The supplied excerpt covers pages 11-15 but does not identify an exact page.",
        ],
    )
    service = RubricServiceWithMarkdown(
        settings,
        subject_context(settings),
        cast(Any, MarkSchemeRecords()),
        cast(Any, SingleQuestionPaperRecords()),
        cast(Any, rubrics),
        cast(Any, None),
        cast(Any, None),
        structured_model=model,
    )

    created = service.create(paper_job_id="paper-1", source_document_id="mark-scheme-1")

    assert created["warnings"] == [
        "The supplied excerpt covers pages 11-15 but does not identify an exact page."
    ]


def test_rubric_creation_rejects_control_characters_in_formula_text() -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingRubrics()
    model = StaticRubricModel(
        [
            {
                "question_number": "01",
                "subpart": "(a)",
                "criterion_id": "01a-B1",
                "scoring_mode": "point_based",
                "mark_type": "B1",
                "max_marks": 1,
                "description": "The vector is \x1b[mathbf{v}.",
                "source_excerpt": r"The vector is \\mathbf{v}.",
                "confidence": 1,
            }
        ]
    )
    service = RubricServiceWithMarkdown(
        settings,
        subject_context(settings),
        cast(Any, MarkSchemeRecords()),
        cast(Any, SingleQuestionPaperRecords()),
        cast(Any, rubrics),
        cast(Any, None),
        cast(Any, None),
        structured_model=model,
    )

    with pytest.raises(ValueError, match="控制字符"):
        service.create(paper_job_id="paper-1", source_document_id="mark-scheme-1")

    assert rubrics.criteria == []


def test_rubric_creation_retries_schema_invalid_control_characters() -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingRubrics()
    model = CorrectingControlCharacterRubricModel()
    service = RubricServiceWithMarkdown(
        settings,
        subject_context(settings),
        cast(Any, MarkSchemeRecords()),
        cast(Any, SingleQuestionPaperRecordsWithBudget()),
        cast(Any, rubrics),
        cast(Any, None),
        cast(Any, None),
        structured_model=model,
    )

    service.create(paper_job_id="paper-1", source_document_id="mark-scheme-1")

    assert model.calls == 2
    assert "failed the rubric schema" in model.prompts[1]
    assert rubrics.criteria[0]["description"] == r"The vector is \mathbf{v}."


def test_rubric_creation_extracts_each_question_within_its_own_timeout() -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingRubrics()
    model = SingleQuestionRubricModel()
    service = RubricServiceWithMarkdown(
        settings,
        subject_context(settings),
        cast(Any, MarkSchemeRecords()),
        cast(Any, PaperRecords()),
        cast(Any, rubrics),
        cast(Any, None),
        cast(Any, None),
        structured_model=model,
    )

    service.create(paper_job_id="paper-1", source_document_id="mark-scheme-1")

    assert sorted(model.calls) == ["01", "16"]
    assert [criterion["question_number"] for criterion in rubrics.criteria] == ["01", "16"]


def test_rubric_creation_rejects_stale_conversion_before_reading_or_model_use() -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingRubrics()
    model = SingleQuestionRubricModel()
    service = RubricServiceWithMarkdown(
        settings,
        subject_context(settings),
        cast(Any, MarkSchemeRecordsWithStaleConversion()),
        cast(Any, PaperRecords()),
        cast(Any, rubrics),
        cast(Any, None),
        cast(Any, None),
        structured_model=model,
    )

    with pytest.raises(ValueError, match="Markdown 与当前来源版本不一致"):
        service.create(paper_job_id="paper-1", source_document_id="mark-scheme-1")

    assert getattr(service, "markdown_reads", 0) == 0
    assert model.calls == []
    assert rubrics.criteria == []


def test_markdown_read_boundary_accepts_versioned_and_legacy_paths(
    tmp_path: Path,
) -> None:
    settings = Settings(
        subject_pack="oxfordaqa-economics-9640",
        object_store_local_root=tmp_path / "objects",
    )
    service = RubricService(
        settings,
        subject_context(settings),
        cast(Any, None),
        cast(Any, None),
        cast(Any, None),
        cast(Any, None),
        cast(Any, None),
    )
    cases = [
        (
            "mark-scheme-v2",
            "source-checksum-v2",
            "mark-scheme-v2/source-checksum-v2.md",
            "# Version 2",
        ),
        (
            "legacy-mark-scheme",
            "legacy-source-checksum",
            "legacy-mark-scheme.md",
            "# Legacy conversion",
        ),
    ]

    for document_id, checksum, stored_path, content in cases:
        path = settings.markdown_dir / stored_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

        assert (
            service._document_markdown(
                {
                    "id": document_id,
                    "markdown_path": stored_path,
                    "converted_source_checksum": checksum,
                },
                expected_checksum=checksum,
            )
            == content
        )

    with pytest.raises(ValueError, match="Markdown 与当前来源版本不一致"):
        service._document_markdown(
            {
                "id": "mark-scheme-v2",
                "markdown_path": "mark-scheme-v2/source-checksum-v2.md",
                "converted_source_checksum": "source-checksum-v1",
            },
            expected_checksum="source-checksum-v2",
        )


def test_markdown_read_boundary_prefers_checksum_specific_s3_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    versioned = tmp_path / "cache" / "versioned.md"
    legacy = tmp_path / "cache" / "legacy.md"
    versioned.parent.mkdir(parents=True)
    versioned.write_text("# Version 2", encoding="utf-8")
    legacy.write_text("# Legacy Version 1", encoding="utf-8")
    requested: list[str] = []

    class FakeS3Backend:
        def materialize(self, key: str) -> Path:
            requested.append(key)
            if key == "corpus/md/mark-scheme-1/source-checksum-v2.md":
                return versioned
            if key == "corpus/md/mark-scheme-1.md":
                return legacy
            raise LookupError("missing")

    monkeypatch.setattr(
        "examtwin.platform.cache_paths.build_storage_backend",
        lambda _settings: FakeS3Backend(),
    )
    settings = Settings(
        subject_pack="oxfordaqa-economics-9640",
        object_store_backend="s3",
        object_store_local_root=tmp_path / "objects",
        object_store_cache_dir=tmp_path / "object-cache",
    )
    service = RubricService(
        settings,
        subject_context(settings),
        cast(Any, None),
        cast(Any, None),
        cast(Any, None),
        cast(Any, None),
        cast(Any, None),
    )

    content = service._document_markdown(
        {
            "id": "mark-scheme-1",
            "markdown_path": "corpus/md/mark-scheme-1/source-checksum-v2.md",
            "converted_source_checksum": "source-checksum-v2",
        },
        expected_checksum="source-checksum-v2",
    )

    assert content == "# Version 2"
    assert requested == ["corpus/md/mark-scheme-1/source-checksum-v2.md"]


def test_rubric_creation_keeps_validated_v1_content_during_v2_replacement(
    tmp_path: Path,
) -> None:
    settings = Settings(
        subject_pack="oxfordaqa-economics-9640",
        object_store_local_root=tmp_path / "objects",
    )
    subject = subject_context(settings)
    source = tmp_path / "mark-scheme.md"
    source.write_text("# Version 1\n\nQuestion 01: B1", encoding="utf-8")
    documents = MutableMarkSchemeRecords(source)
    ingestor = CorpusIngestor(cast(Any, documents), settings, subject)
    v1_path, v1_created = ingestor.convert(documents.get("mark-scheme-1"))
    assert v1_created is True

    read_ready = Event()
    resume_read = Event()
    rubrics = CapturingRubrics()
    model = SingleQuestionRubricModel()
    service = PausingRubricService(
        settings,
        subject,
        cast(Any, documents),
        cast(Any, SingleQuestionPaperRecords()),
        cast(Any, rubrics),
        cast(Any, None),
        cast(Any, None),
        structured_model=model,
        read_ready=read_ready,
        resume_read=resume_read,
    )
    results: list[dict[str, object]] = []
    errors: list[Exception] = []

    def create_rubric() -> None:
        try:
            results.append(
                service.create(
                    paper_job_id="paper-1",
                    source_document_id="mark-scheme-1",
                )
            )
        except Exception as error:
            errors.append(error)

    thread = Thread(target=create_rubric)
    thread.start()
    try:
        assert read_ready.wait(timeout=5)
        source.write_text("# Version 2\n\nQuestion 01: B2", encoding="utf-8")
        documents.replace_source("mark-scheme-checksum-v2")
        v2_path, v2_created = ingestor.convert(documents.get("mark-scheme-1"))
        assert v2_created is True
    finally:
        resume_read.set()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert errors == []
    assert results[0]["source_document_checksum"] == "mark-scheme-checksum-v1"
    assert model.calls == ["01"]
    assert "# Version 1" in model.prompts[0]
    assert "# Version 2" not in model.prompts[0]
    assert "# Version 1" in Path(v1_path).read_text(encoding="utf-8")
    assert "# Version 2" not in Path(v1_path).read_text(encoding="utf-8")
    assert "# Version 2" in Path(v2_path).read_text(encoding="utf-8")
    assert documents.document["markdown_path"] == ("mark-scheme-1/mark-scheme-checksum-v2.md")


@pytest.mark.parametrize(
    ("papers", "documents", "message"),
    [
        (
            PaperRecordsWithoutIdentity(),
            MarkSchemeRecords(),
            "Question Paper 缺少完整考试身份",
        ),
        (
            PaperRecords(),
            MarkSchemeRecordsWithoutIdentity(),
            "Mark Scheme 缺少完整考试身份",
        ),
        (
            PaperRecords(),
            MarkSchemeRecordsWithConflict(),
            "Mark Scheme 与试卷的年份、考季或 Unit 不匹配",
        ),
    ],
)
def test_rubric_creation_requires_complete_matching_pair_identity(
    papers: object,
    documents: object,
    message: str,
) -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    service = RubricServiceWithMarkdown(
        settings,
        subject_context(settings),
        cast(Any, documents),
        cast(Any, papers),
        cast(Any, CapturingRubrics()),
        cast(Any, None),
        cast(Any, None),
        structured_model=RubricModelWithPrintedQuestionLabels(),
    )

    with pytest.raises(ValueError, match=message):
        service.create(paper_job_id="paper-1", source_document_id="mark-scheme-1")


def test_rubric_repository_persists_set_before_its_criteria() -> None:
    sessions = FlushOrderingSessions()
    repository = RubricRepositoryWithoutReadback(cast(Any, sessions))

    repository.create(
        subject_id="subject-1",
        paper_job_id="paper-1",
        source_document_id="mark-scheme-1",
        source_document_checksum="mark-scheme-checksum-v1",
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


@pytest.mark.integration
def test_criterion_review_is_subject_scoped_audited_and_required_before_confirmation() -> None:
    settings = get_settings()
    upgrade_database(settings.database_url)
    sessions = create_session_factory(settings.database_url)
    token = uuid.uuid4().hex
    subject_id = f"subject-{token}"
    other_subject_id = f"other-subject-{token}"
    paper_id = f"paper-{token}"
    document_id = f"mark-scheme-{token}"
    now = utcnow()
    with sessions.begin() as session:
        session.add_all(
            [
                SubjectModel(
                    id=subject_id,
                    subject_code=f"A{token[:8]}",
                    title="Audit subject",
                    board_name="Test board",
                    created_at=now,
                    updated_at=now,
                ),
                SubjectModel(
                    id=other_subject_id,
                    subject_code=f"B{token[:8]}",
                    title="Other subject",
                    board_name="Test board",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                PaperJobModel(
                    id=paper_id,
                    subject_pack_id="test-pack",
                    subject_code=f"A{token[:8]}",
                    filename="paper.pdf",
                    suffix=".pdf",
                    unit_code="U1",
                    source_path="paper-source",
                    status="completed",
                    stage="completed",
                    error=None,
                    created_at=now,
                    updated_at=now,
                ),
                SourceDocumentModel(
                    id=document_id,
                    subject_code=f"A{token[:8]}",
                    subject_id=subject_id,
                    path=f"/source/{token}.pdf",
                    filename="mark-scheme.pdf",
                    source_type="mark_scheme",
                    status="converted",
                    checksum=token,
                ),
            ]
        )

    repository = RubricRepository(sessions)
    created = repository.create(
        subject_id=subject_id,
        paper_job_id=paper_id,
        source_document_id=document_id,
        source_document_checksum=token,
        identity={"pair_key": "test:2024:JUN:U1"},
        parser_model="fake-rubric-model",
        warnings=[],
        criteria=[
            {
                "question_number": "1",
                "criterion_id": "1-B1",
                "scoring_mode": "point_based",
                "max_marks": 1,
                "description": "Original criterion.",
                "source_excerpt": "B1",
                "confidence": 1,
            }
        ],
    )
    rubric_id = str(created["id"])
    criterion_id = str(created["criteria"][0]["id"])
    try:
        with pytest.raises(LookupError):
            repository.get(rubric_id, subject_id=other_subject_id)
        with pytest.raises(ValueError, match="仍有未审核"):
            repository.confirm(rubric_id, subject_id=subject_id, reviewer="Teacher")

        reviewed = repository.review_criterion(
            rubric_id,
            criterion_id,
            subject_id=subject_id,
            review_status="accepted",
            reviewer="Teacher",
            note="Corrected wording against the official source.",
            updates={"description": "Edited criterion."},
        )
        criterion = reviewed["criteria"][0]
        assert criterion["description"] == "Edited criterion."
        assert criterion["reviewed_by"] == "Teacher"
        confirmed = repository.confirm(
            rubric_id,
            subject_id=subject_id,
            reviewer="Teacher",
        )
        assert confirmed["status"] == "confirmed"
        assert confirmed["confirmed_by"] == "Teacher"

        with sessions() as session:
            audit = (
                session.query(RubricCriterionReviewModel).filter_by(criterion_id=criterion_id).one()
            )
            assert audit.action == "edited_and_accepted"
            assert audit.reviewer == "Teacher"
            assert "Original criterion." in audit.before_json
            assert "Edited criterion." in audit.after_json
    finally:
        with sessions.begin() as session:
            session.query(RubricCriterionReviewModel).filter_by(rubric_set_id=rubric_id).delete()
            session.query(RubricCriterionModel).filter_by(rubric_set_id=rubric_id).delete()
            session.query(RubricSetModel).filter_by(id=rubric_id).delete()
            session.query(SourceDocumentModel).filter_by(id=document_id).delete()
            session.query(PaperJobModel).filter_by(id=paper_id).delete()
            session.query(SubjectModel).filter(
                SubjectModel.id.in_([subject_id, other_subject_id])
            ).delete(synchronize_session=False)


class CapturingReviewRubrics:
    def __init__(
        self,
        subject_id: str,
        *,
        status: str = "draft",
        criteria: list[dict[str, object]] | None = None,
    ) -> None:
        self.batch_calls: list[dict[str, object]] = []
        self.ai_calls: list[dict[str, object]] = []
        self.rubric = {
            "id": "rubric-1",
            "subject_id": subject_id,
            "paper_job_id": "paper-1",
            "source_document_id": "mark-scheme-1",
            "source_document_checksum": "mark-scheme-checksum-v1",
            "identity": {"pair_key": "9640:2024:JUN:U1"},
            "status": status,
            "criteria": criteria
            or [
                {
                    "id": "criterion-1",
                    "criterion_id": "1-B1",
                    "question_number": "1",
                    "description": "Award for identifying the effect.",
                    "criterion_fingerprint": "a" * 64,
                    "max_marks": 2.0,
                    "review_status": "pending",
                    "ai_review": {"criterion_fingerprint": "c" * 64},
                },
                {
                    "id": "criterion-2",
                    "question_number": "1",
                    "criterion_id": "1-B2",
                    "description": "Award for explaining the effect.",
                    "criterion_fingerprint": "b" * 64,
                    "max_marks": 3.0,
                    "review_status": "pending",
                },
            ],
        }

    def review_criteria_batch(
        self,
        rubric_id: str,
        **values: object,
    ) -> dict[str, object]:
        self.batch_calls.append({"rubric_id": rubric_id, **values})
        return self.rubric

    def get(self, rubric_id: str, *, subject_id: str) -> dict[str, object]:
        assert rubric_id == self.rubric["id"]
        assert subject_id == self.rubric["subject_id"]
        return self.rubric

    def record_ai_reviews(
        self,
        rubric_id: str,
        **values: object,
    ) -> dict[str, object]:
        self.ai_calls.append({"rubric_id": rubric_id, **values})
        return self.rubric


class ReviewPaperRecords:
    def get(self, paper_job_id: str) -> dict[str, object]:
        assert paper_job_id == "paper-1"
        return {"id": paper_job_id, "subject_code": "9640"}

    def questions(self, paper_job_id: str) -> list[dict[str, object]]:
        assert paper_job_id == "paper-1"
        return [
            {
                "position": 1,
                "number": "1",
                "question_markdown": "Explain the effect of a tax.",
            },
            {
                "position": 2,
                "number": "2",
                "question_markdown": "Evaluate the policy.",
            },
            {
                "position": 3,
                "number": "3",
                "question_markdown": "Calculate the change.",
            },
        ]


class ReviewMarkSchemeRecords:
    def __init__(self, **updates: object) -> None:
        self.document: dict[str, object] = {
            "id": "mark-scheme-1",
            "subject_code": "9640",
            "source_type": "mark_scheme",
            "checksum": "mark-scheme-checksum-v1",
            "converted_source_checksum": "mark-scheme-checksum-v1",
            "pair_key": "9640:2024:JUN:U1",
            "identity_status": "complete",
            "filename": "A-Level-AQA经济学-国际卷MS-202406-Economics-U1-AQA.pdf",
        }
        self.document.update(updates)

    def get(self, document_id: str) -> dict[str, object]:
        assert document_id == "mark-scheme-1"
        return dict(self.document)


class FixedAiReviewModel:
    model_name = "fake-ai-review-model"

    def __init__(self, reviews: list[dict[str, object]]) -> None:
        self.reviews = reviews
        self.calls = 0

    def complete(
        self,
        messages: Sequence[HarnessMessage],
        response_model: type[StructuredResultT],
        *,
        timeout: float,
    ) -> StructuredResultT:
        self.calls += 1
        assert timeout > 0
        rubric_message = next(
            message.content for message in messages if "CURRENT RUBRIC CRITERIA" in message.content
        )
        assert '"review_id": "criterion-1"' in rubric_message
        assert '"criterion_label": "1-B1"' in rubric_message
        assert '"id": "criterion-1"' not in rubric_message
        assert '"criterion_id": "1-B1"' not in rubric_message
        assert "criterion_fingerprint" not in rubric_message
        assert "ai_review" not in rubric_message
        return response_model.model_validate({"reviews": self.reviews})


class SequencedAiReviewModel(FixedAiReviewModel):
    def __init__(self, responses: list[list[dict[str, object]]]) -> None:
        super().__init__([])
        self.responses = responses

    def complete(
        self,
        messages: Sequence[HarnessMessage],
        response_model: type[StructuredResultT],
        *,
        timeout: float,
    ) -> StructuredResultT:
        self.reviews = self.responses[min(self.calls, len(self.responses) - 1)]
        return super().complete(messages, response_model, timeout=timeout)


class OverviewAssessments:
    def for_paper(self, paper_job_id: str, *, subject_code: str) -> list[dict[str, object]]:
        assert paper_job_id == "paper-1"
        assert subject_code == "9640"
        return [
            {
                "id": "q1-old",
                "paper_job_id": paper_job_id,
                "question_position": 1,
                "rubric_set_id": "rubric-1",
                "status": "pending_review",
                "total_awarded": 1.0,
                "total_available": 5.0,
                "confidence": 0.4,
                "created_at": "2026-08-01T00:00:00Z",
                "result": {
                    "status": "pending_review",
                    "total_awarded": 1.0,
                    "total_available": 5.0,
                    "confidence": 0.4,
                    "manual_review_required": True,
                    "rubric_awards": [
                        {
                            "error_types": ["conceptual"],
                            "improvement_suggestion": "Review the concept.",
                        }
                    ],
                },
            },
            {
                "id": "q1-new",
                "paper_job_id": paper_job_id,
                "question_position": 1,
                "rubric_set_id": "rubric-1",
                "status": "overridden",
                "total_awarded": 4.0,
                "total_available": 5.0,
                "confidence": 0.9,
                "created_at": "2026-08-03T00:00:00Z",
                "result": {
                    "status": "overridden",
                    "total_awarded": 4.0,
                    "total_available": 5.0,
                    "confidence": 0.9,
                    "manual_review_required": False,
                    "improvement_suggestions": ["Include the unit.", "Include the unit."],
                    "rubric_awards": [
                        {
                            "error_types": ["unit"],
                            "improvement_suggestion": "Include the unit.",
                        }
                    ],
                },
            },
            {
                "id": "q2-other-rubric",
                "paper_job_id": paper_job_id,
                "question_position": 2,
                "rubric_set_id": "rubric-other",
                "status": "confirmed",
                "total_awarded": 4.0,
                "total_available": 4.0,
                "confidence": 1.0,
                "created_at": "2026-08-04T00:00:00Z",
                "result": {
                    "status": "confirmed",
                    "total_awarded": 4.0,
                    "total_available": 4.0,
                    "confidence": 1.0,
                    "manual_review_required": False,
                    "rubric_awards": [],
                },
            },
            {
                "id": "q2-current",
                "paper_job_id": paper_job_id,
                "question_position": 2,
                "rubric_set_id": "rubric-1",
                "status": "pending_review",
                "total_awarded": 2.0,
                "total_available": 4.0,
                "confidence": 0.7,
                "created_at": "2026-08-02T00:00:00Z",
                "result": {
                    "status": "pending_review",
                    "total_awarded": 2.0,
                    "total_available": 4.0,
                    "confidence": 0.7,
                    "manual_review_required": True,
                    "rubric_awards": [
                        {
                            "error_types": ["omission"],
                            "improvement_suggestion": "Complete the evaluation.",
                        }
                    ],
                },
            },
        ]


def _review_service(
    rubrics: CapturingReviewRubrics,
    *,
    model: FixedAiReviewModel | None = None,
    assessments: object | None = None,
    documents: object | None = None,
) -> RubricService:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    return RubricServiceWithMarkdown(
        settings,
        subject_context(settings),
        cast(Any, documents or ReviewMarkSchemeRecords()),
        cast(Any, ReviewPaperRecords()),
        cast(Any, rubrics),
        cast(Any, assessments),
        cast(Any, None),
        structured_model=model,
    )


def test_batch_rubric_review_delegates_mixed_decisions_once() -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingReviewRubrics(subject_context(settings).id)
    service = _review_service(rubrics)

    service.review_criteria_batch(
        "rubric-1",
        BatchReviewRubricCriteriaRequest.model_validate(
            {
                "reviewer": "Teacher",
                "decisions": [
                    {
                        "criterion_id": "criterion-1",
                        "review_status": "accepted",
                        "updates": {"description": "Clarified criterion."},
                    },
                    {
                        "criterion_id": "criterion-2",
                        "review_status": "rejected",
                        "note": "Duplicate mark.",
                    },
                ],
            }
        ),
    )

    assert len(rubrics.batch_calls) == 1
    assert rubrics.batch_calls[0]["reviewer"] == "Teacher"
    assert rubrics.batch_calls[0]["decisions"] == [
        {
            "criterion_id": "criterion-1",
            "review_status": "accepted",
            "note": None,
            "updates": {"description": "Clarified criterion."},
        },
        {
            "criterion_id": "criterion-2",
            "review_status": "rejected",
            "note": "Duplicate mark.",
            "updates": {},
        },
    ]


def test_batch_rubric_review_forwards_supplied_criterion_fingerprint() -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingReviewRubrics(subject_context(settings).id)
    service = _review_service(rubrics)
    fingerprint = "a" * 64

    service.review_criteria_batch(
        "rubric-1",
        BatchReviewRubricCriteriaRequest.model_validate(
            {
                "reviewer": "Teacher",
                "decisions": [
                    {
                        "criterion_id": "criterion-1",
                        "expected_criterion_fingerprint": fingerprint,
                        "review_status": "accepted",
                    }
                ],
            }
        ),
    )

    assert rubrics.batch_calls[0]["decisions"] == [
        {
            "criterion_id": "criterion-1",
            "expected_criterion_fingerprint": fingerprint,
            "review_status": "accepted",
            "note": None,
            "updates": {},
        }
    ]


@pytest.mark.parametrize(
    "source_updates",
    [
        {"checksum": "mark-scheme-checksum-v2"},
        {
            "pair_key": "9640:2023:JUN:U1",
            "filename": "A-Level-AQA经济学-国际卷MS-202306-Economics-U1-AQA.pdf",
        },
    ],
)
def test_ai_review_rejects_changed_source_before_reading_or_writing(
    source_updates: dict[str, object],
) -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingReviewRubrics(subject_context(settings).id)
    model = FixedAiReviewModel([])
    service = _review_service(
        rubrics,
        model=model,
        documents=ReviewMarkSchemeRecords(**source_updates),
    )

    with pytest.raises(RubricConflictError, match="Mark Scheme 已发生变化"):
        service.ai_review_criteria(
            "rubric-1",
            AiReviewRubricCriteriaRequest(criterion_ids=["criterion-1"]),
        )

    assert getattr(service, "markdown_reads", 0) == 0
    assert model.calls == 0
    assert rubrics.ai_calls == []


def test_ai_review_rejects_stale_conversion_before_reading_or_writing() -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingReviewRubrics(subject_context(settings).id)
    model = FixedAiReviewModel([])
    service = _review_service(
        rubrics,
        model=model,
        documents=ReviewMarkSchemeRecords(converted_source_checksum="mark-scheme-checksum-v0"),
    )

    with pytest.raises(ValueError, match="Markdown 与当前来源版本不一致"):
        service.ai_review_criteria(
            "rubric-1",
            AiReviewRubricCriteriaRequest(criterion_ids=["criterion-1"]),
        )

    assert getattr(service, "markdown_reads", 0) == 0
    assert model.calls == 0
    assert rubrics.ai_calls == []


def test_ai_review_id_mismatch_writes_nothing() -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingReviewRubrics(subject_context(settings).id)
    service = _review_service(
        rubrics,
        model=FixedAiReviewModel(
            [
                {
                    "review_id": "criterion-1",
                    "recommendation": "accept",
                    "confidence": 0.9,
                    "rationale": "Matches the Mark Scheme.",
                }
            ]
        ),
    )

    with pytest.raises(AiReviewModelError, match="ID 不闭合"):
        service.ai_review_criteria(
            "rubric-1",
            AiReviewRubricCriteriaRequest(criterion_ids=["criterion-1", "criterion-2"]),
        )

    assert rubrics.ai_calls == []


def test_ai_review_repairs_missing_review_id_once() -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingReviewRubrics(subject_context(settings).id)
    model = SequencedAiReviewModel(
        [
            [
                {
                    "review_id": "criterion-1",
                    "recommendation": "accept",
                    "confidence": 0.9,
                    "rationale": "Matches the Mark Scheme.",
                }
            ],
            [
                {
                    "review_id": "criterion-1",
                    "recommendation": "accept",
                    "confidence": 0.9,
                    "rationale": "Matches the Mark Scheme.",
                },
                {
                    "review_id": "criterion-2",
                    "recommendation": "accept",
                    "confidence": 0.9,
                    "rationale": "Matches the Mark Scheme.",
                },
            ],
        ]
    )
    service = _review_service(rubrics, model=model)

    service.ai_review_criteria(
        "rubric-1",
        AiReviewRubricCriteriaRequest(criterion_ids=["criterion-1", "criterion-2"]),
    )

    assert model.calls == 2
    reviews = cast(list[dict[str, object]], rubrics.ai_calls[0]["reviews"])
    assert [review["criterion_id"] for review in reviews] == [
        "criterion-1",
        "criterion-2",
    ]


def test_ai_review_ignores_null_placeholder_update_fields() -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingReviewRubrics(subject_context(settings).id)
    service = _review_service(
        rubrics,
        model=FixedAiReviewModel(
            [
                {
                    "review_id": "criterion-1",
                    "recommendation": "accept",
                    "confidence": 0.95,
                    "rationale": "Directly supported.",
                    "suggested_updates": {
                        "description": None,
                        "alternatives": None,
                        "units": None,
                    },
                },
                {
                    "review_id": "criterion-2",
                    "recommendation": "revise",
                    "confidence": 0.8,
                    "rationale": "The description is too broad.",
                    "suggested_updates": {
                        "description": "Award for the explained effect.",
                        "dependencies": None,
                        "alternatives": None,
                    },
                },
            ]
        ),
    )

    service.ai_review_criteria(
        "rubric-1",
        AiReviewRubricCriteriaRequest(criterion_ids=["criterion-1", "criterion-2"]),
    )

    reviews = cast(list[dict[str, object]], rubrics.ai_calls[0]["reviews"])
    assert reviews[0]["suggested_updates"] is None
    assert reviews[1]["suggested_updates"] == {"description": "Award for the explained effect."}


def test_ai_review_repairs_revise_without_actionable_updates_once() -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingReviewRubrics(subject_context(settings).id)
    model = SequencedAiReviewModel(
        [
            [
                {
                    "review_id": "criterion-1",
                    "recommendation": "revise",
                    "confidence": 0.8,
                    "rationale": "The description is too broad.",
                    "suggested_updates": {"description": "Award for identifying the effect."},
                },
                {
                    "review_id": "criterion-2",
                    "recommendation": "accept",
                    "confidence": 0.95,
                    "rationale": "Directly supported.",
                },
            ],
            [
                {
                    "review_id": "criterion-1",
                    "recommendation": "revise",
                    "confidence": 0.8,
                    "rationale": "The description is too broad.",
                    "suggested_updates": {"description": "Award for the explained effect."},
                },
                {
                    "review_id": "criterion-2",
                    "recommendation": "accept",
                    "confidence": 0.95,
                    "rationale": "Directly supported.",
                },
            ],
        ]
    )
    service = _review_service(rubrics, model=model)

    service.ai_review_criteria(
        "rubric-1",
        AiReviewRubricCriteriaRequest(criterion_ids=["criterion-1", "criterion-2"]),
    )

    assert model.calls == 2
    reviews = cast(list[dict[str, object]], rubrics.ai_calls[0]["reviews"])
    assert reviews[0]["suggested_updates"] == {"description": "Award for the explained effect."}


def test_ai_review_success_persists_once_without_changing_human_state() -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingReviewRubrics(subject_context(settings).id)
    service = _review_service(
        rubrics,
        model=FixedAiReviewModel(
            [
                {
                    "review_id": "criterion-1",
                    "recommendation": "accept",
                    "confidence": 0.95,
                    "rationale": "Directly supported.",
                },
                {
                    "review_id": "criterion-2",
                    "recommendation": "revise",
                    "confidence": 0.8,
                    "rationale": "The description is too broad.",
                    "suggested_updates": {"description": "Award for the explained effect."},
                },
            ]
        ),
    )

    result = service.ai_review_criteria(
        "rubric-1",
        AiReviewRubricCriteriaRequest(criterion_ids=["criterion-1", "criterion-2"]),
    )

    assert len(rubrics.ai_calls) == 1
    assert rubrics.ai_calls[0]["model"] == "fake-ai-review-model"
    assert [
        review["criterion_fingerprint"]
        for review in cast(list[dict[str, object]], rubrics.ai_calls[0]["reviews"])
    ] == ["a" * 64, "b" * 64]
    assert [
        review["criterion_id"]
        for review in cast(list[dict[str, object]], rubrics.ai_calls[0]["reviews"])
    ] == ["criterion-1", "criterion-2"]
    assert [
        criterion["review_status"]
        for criterion in cast(list[dict[str, object]], result["criteria"])
    ] == ["pending", "pending"]
    assert getattr(service, "markdown_reads", 0) == 1


def test_grading_overview_uses_latest_exact_rubric_and_persisted_override() -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingReviewRubrics(
        subject_context(settings).id,
        status="confirmed",
        criteria=[
            {
                "id": "criterion-1",
                "question_number": "1",
                "max_marks": 5.0,
                "review_status": "accepted",
            },
            {
                "id": "criterion-2",
                "question_number": "2",
                "max_marks": 4.0,
                "review_status": "accepted",
            },
            {
                "id": "criterion-3",
                "question_number": "3",
                "max_marks": 3.0,
                "review_status": "accepted",
            },
        ],
    )
    service = _review_service(rubrics, assessments=OverviewAssessments())

    overview = service.grading_overview("paper-1", "rubric-1")

    assert overview["total_awarded"] == 6.0
    assert overview["total_available"] == 12.0
    assert overview["percentage"] == 50.0
    assert overview["completed_questions"] == 2
    assert overview["total_questions"] == 3
    assert overview["pending_review_count"] == 1
    assert overview["overridden_count"] == 1
    assert overview["incomplete"] is True
    assert overview["common_error_types"] == ["unit", "omission"]
    questions = cast(list[dict[str, object]], overview["questions"])
    assert [(item["position"], item["status"]) for item in questions] == [
        (1, "overridden"),
        (2, "pending_review"),
        (3, "unassessed"),
    ]
    assert questions[0]["awarded"] == 4.0
    assert questions[0]["suggestions"] == ["Include the unit."]
    assert questions[2]["available"] == 3.0


@pytest.mark.parametrize(
    "status,warnings,expected",
    [
        ("pending_review", [], "provisional"),
        ("pending_review", ["相关评分原子已暂缓授分"], "unavailable"),
        ("confirmed", ["相关评分原子已暂缓授分"], "reviewed"),
        ("overridden", [], "reviewed"),
    ],
)
def test_overview_grade_uses_exact_identity_and_human_review(status, warnings, expected):
    from types import SimpleNamespace

    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    rubrics = CapturingReviewRubrics(subject_context(settings).id, status="confirmed")
    rubrics.rubric["identity"] = {"pair_key": "9640:2024:JAN:U1"}
    assessments = SimpleNamespace(
        for_paper=lambda *args, **kwargs: [
            {
                "id": "assessment",
                "rubric_set_id": "rubric-1",
                "question_position": 1,
                "status": status,
                "total_awarded": 58,
                "total_available": 80,
                "confidence": 0.9,
                "result": {"warnings": warnings},
            }
        ]
    )
    service = _review_service(rubrics, assessments=assessments)
    service.papers = cast(
        Any,
        SimpleNamespace(
            get=lambda _: {"subject_code": "9640", "pair_key": "9640:2024:JAN:U1"},
            questions=lambda _: [{"position": 1, "number": "1"}],
        ),
    )
    overview = service.grading_overview("paper-1", "rubric-1")
    assert overview["grade_estimate"]["status"] == expected
    assert overview["grade_estimate"]["grade"] == (None if expected == "unavailable" else "A")
    assert overview["total_awarded"] == 58


class GradeQuestionPapers:
    def get(self, paper_job_id: str) -> dict[str, object]:
        assert paper_job_id == "paper-1"
        return {
            "subject_code": "9640",
            "pair_key": "9640:2024:JUN:U1",
            "knowledge_base_version_ids_json": "[]",
            "graph_version_id": None,
        }

    def questions(self, paper_job_id: str) -> list[dict[str, object]]:
        assert paper_job_id == "paper-1"
        return [
            {
                "position": 0,
                "number": "1",
                "status": "completed",
                "question_markdown": "State the answer.",
                "answer_json": (
                    '{"number":"1","question_markdown":"State the answer.",'
                    '"answer_markdown":"The answer is B.","confidence":1,'
                    '"grounded":true}'
                ),
                "knowledge_codes_json": "[]",
            }
        ]


class GradeQuestionRubrics:
    def get(self, rubric_id: str, *, subject_id: str) -> dict[str, object]:
        assert rubric_id == "rubric-1"
        assert subject_id == "oxfordaqa-economics-9640"
        return {
            "id": rubric_id,
            "subject_id": subject_id,
            "paper_job_id": "paper-1",
            "status": "confirmed",
        }

    def accepted_for_question(
        self,
        rubric_id: str,
        question_number: str,
        *,
        subject_id: str,
    ) -> list[dict[str, object]]:
        assert rubric_id == "rubric-1"
        assert question_number == "1"
        assert subject_id == "oxfordaqa-economics-9640"
        reviewed_at = utcnow()
        return [
            {
                "id": "criterion-row-1",
                "question_number": "1",
                "subpart": "whole",
                "criterion_id": "1-B1",
                "scoring_mode": "point_based",
                "mark_type": "B1",
                "max_marks": 1.0,
                "description": "Award one mark for B.",
                "dependencies": [],
                "alternatives": [],
                "accuracy_requirement": None,
                "units": [],
                "follow_through_policy": None,
                "source_page": 1,
                "source_excerpt": "B1",
                "confidence": 1.0,
                "review_status": "accepted",
                "reviewed_by": "Reviewer",
                "reviewed_at": reviewed_at,
                "criterion_fingerprint": "fingerprint",
                "ai_review": {
                    "recommendation": "accept",
                    "reviewed_at": reviewed_at,
                },
            }
        ]


class CapturingGradeQuestion:
    def __init__(self) -> None:
        self.request: object | None = None
        self.evidence: dict[str, Any] = {}

    def grade(self, request: object, **kwargs: Any) -> object:
        self.request = request
        self.evidence = kwargs
        return type("GradeResult", (), {"assessment_id": "assessment-1"})()


class CapturingAssessmentContext:
    def link_context(self, *_args: object, **_kwargs: object) -> None:
        return None


def test_grade_question_serializes_only_scoring_criterion_fields() -> None:
    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    grading = CapturingGradeQuestion()
    service = RubricService(
        settings,
        subject_context(settings),
        cast(Any, None),
        cast(Any, GradeQuestionPapers()),
        cast(Any, GradeQuestionRubrics()),
        cast(Any, CapturingAssessmentContext()),
        cast(Any, grading),
    )

    result = service.grade_question("paper-1", 0, rubric_set_id="rubric-1")

    assert result.assessment_id == "assessment-1"
    request = cast(Any, grading.request)
    assert request.max_marks == 1.0
    assert '"criterion_id": "1-B1"' in request.mark_scheme_markdown
    assert "reviewed_at" not in request.mark_scheme_markdown
    assert "review_status" not in request.mark_scheme_markdown
    assert "ai_review" not in request.mark_scheme_markdown
    assert grading.evidence["confirmed_criteria"][0]["criterion_id"] == "1-B1"
    assert grading.evidence["answer_diagrams"] == []
    assert grading.evidence["answer_images"] == []


def test_grade_question_forwards_actual_persisted_artifacts() -> None:
    class ArtifactPapers(GradeQuestionPapers):
        def questions(self, paper_job_id: str) -> list[dict[str, object]]:
            rows = super().questions(paper_job_id)
            answer = json.loads(str(rows[0]["answer_json"]))
            answer["diagrams"] = [
                {
                    "title": "Actual vector",
                    "elements": [{"kind": "line", "x1": 0, "y1": 0, "x2": 40, "y2": 20}],
                }
            ]
            answer["images"] = [
                {
                    "title": "Actual image",
                    "content_url": "/api/v1/answer-assets/" + "a" * 32 + ".png",
                }
            ]
            rows[0]["answer_json"] = json.dumps(answer)
            return rows

    settings = Settings(subject_pack="oxfordaqa-economics-9640")
    grading = CapturingGradeQuestion()
    service = RubricService(
        settings,
        subject_context(settings),
        cast(Any, None),
        cast(Any, ArtifactPapers()),
        cast(Any, GradeQuestionRubrics()),
        cast(Any, CapturingAssessmentContext()),
        cast(Any, grading),
    )
    service.grade_question("paper-1", 0, rubric_set_id="rubric-1")
    assert grading.evidence["answer_diagrams"][0].elements[0].x2 == 40
    assert grading.evidence["answer_images"][0].content_url.endswith("a" * 32 + ".png")


class AssessmentProjectionSession:
    def __init__(self, row: object) -> None:
        self.row = row

    def __enter__(self) -> AssessmentProjectionSession:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def scalars(self, _statement: object) -> list[object]:
        return [self.row]


class AssessmentProjectionSessions:
    def __init__(self, row: object) -> None:
        self.session = AssessmentProjectionSession(row)

    def __call__(self) -> AssessmentProjectionSession:
        return self.session


class AssessmentProjectionRow:
    id = "assessment-1"
    paper_job_id = "paper-1"
    question_position = 1
    rubric_set_id = "rubric-1"
    status = "overridden"
    total_awarded = 4.0
    total_available = 5.0
    confidence = 0.9
    result_json = (
        '{"status":"pending_review","total_awarded":2.0,"total_available":5.0,'
        '"confidence":0.5,"manual_review_required":true,'
        '"warnings":["Keep historical review detail."]}'
    )
    created_at = "2026-08-03T00:00:00Z"


@pytest.mark.parametrize(
    ("status", "manual_review_required"),
    [("pending_review", True), ("confirmed", False), ("overridden", False)],
)
def test_assessment_for_paper_projects_persisted_final_result(
    status: str,
    manual_review_required: bool,
) -> None:
    row = AssessmentProjectionRow()
    row.status = status
    repository = AssessmentRepository(cast(Any, AssessmentProjectionSessions(row)))

    result = repository.for_paper("paper-1", subject_code="9640")

    assert result[0]["status"] == status
    assert result[0]["total_awarded"] == 4.0
    assert result[0]["total_available"] == 5.0
    assert result[0]["confidence"] == 0.9
    assert result[0]["result"] == {
        "status": status,
        "total_awarded": 4.0,
        "total_available": 5.0,
        "confidence": 0.9,
        "manual_review_required": manual_review_required,
        "warnings": ["Keep historical review detail."],
    }
