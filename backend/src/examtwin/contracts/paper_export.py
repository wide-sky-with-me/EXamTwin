"""Read-only original-paper layout used by the answer PDF preview."""

from pydantic import Field

from examtwin.contracts.base import SerializedResponse


class PaperAnswerRegion(SerializedResponse):
    question_position: int
    answer_anchor: str
    page_number: int
    x: float
    y: float
    width: float
    height: float


class PaperExportPage(SerializedResponse):
    page_number: int
    width: float
    height: float


class PaperExportLayout(SerializedResponse):
    source_sha256: str
    pages: list[PaperExportPage]
    regions: list[PaperAnswerRegion] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
