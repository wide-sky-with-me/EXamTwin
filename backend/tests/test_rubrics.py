from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, TypeVar, cast

import pytest
from examtwin.assessment.rubric_repository import RubricRepository
from examtwin.assessment.rubrics import RubricService
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

    service.create(paper_job_id="paper-1", source_document_id="mark-scheme-1")

    assert [criterion["question_number"] for criterion in rubrics.criteria] == ["01", "16"]
    assert [criterion["subpart"] for criterion in rubrics.criteria] == ["whole", "1"]


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
