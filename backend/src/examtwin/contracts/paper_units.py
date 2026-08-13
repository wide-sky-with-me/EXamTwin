from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from examtwin.contracts.base import SerializedResponse
from examtwin.contracts.papers import PaperJobCreated

PaperUnitDocumentRole = Literal["question_paper", "mark_scheme", "source_booklet"]


class PaperUnitDocument(SerializedResponse):
    id: str
    filename: str
    display_name: str | None = None
    role: PaperUnitDocumentRole
    source_type: Literal["question_paper", "mark_scheme", "insert"]
    status: str
    checksum: str
    page_count: int | None = None


class PaperUnitSummary(SerializedResponse):
    id: str
    subject_id: str
    subject_code: str
    pair_key: str
    display_name: str | None = None
    unit_code: str
    exam_year: int
    exam_session: str
    status: Literal["active", "archived"]
    documents: list[PaperUnitDocument] = Field(default_factory=list)
    paper_job_count: int = Field(ge=0)
    created_at: str
    updated_at: str


class PaperUnitListResponse(SerializedResponse):
    items: list[PaperUnitSummary]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    available_units: list[str] = Field(default_factory=list)
    available_years: list[int] = Field(default_factory=list)
    available_sessions: list[str] = Field(default_factory=list)


class CreatePaperUnitRequest(SerializedResponse):
    document_ids: list[str] = Field(min_length=1, max_length=20)
    display_name: str | None = Field(default=None, max_length=200)


class UpdatePaperUnitRequest(SerializedResponse):
    display_name: str | None = Field(default=None, max_length=200)
    document_ids: list[str] | None = Field(default=None, min_length=1, max_length=20)

    @model_validator(mode="after")
    def require_change(self) -> UpdatePaperUnitRequest:
        if "display_name" not in self.model_fields_set and self.document_ids is None:
            raise ValueError("至少提供一个需要更新的字段")
        return self


class CreatePaperUnitAnswerRequest(SerializedResponse):
    question_paper_document_id: str
    source_booklet_document_id: str | None = None
    knowledge_base_version_ids: list[str] = Field(default_factory=list, max_length=20)
    include_supplementary: bool = False


class PaperUnitAnswerCreated(PaperJobCreated):
    paper_unit_id: str
    question_paper_document_id: str
