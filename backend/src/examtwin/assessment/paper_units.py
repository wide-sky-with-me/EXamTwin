from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from examtwin.assessment.paper_unit_repository import PaperUnitRepository
from examtwin.knowledge.public import CorpusRepository
from examtwin.subjects.public import SubjectContext

_ROLE_BY_SOURCE_TYPE = {
    "question_paper": "question_paper",
    "mark_scheme": "mark_scheme",
    "insert": "source_booklet",
}


class PaperUnitService:
    """Manage strict exam identities separately from their source-document inventory."""

    def __init__(
        self,
        subject: SubjectContext,
        units: PaperUnitRepository,
        documents: CorpusRepository,
    ) -> None:
        self.subject = subject
        self.units = units
        self.documents = documents

    def list_units(
        self,
        *,
        query: str | None = None,
        unit_code: str | None = None,
        exam_year: int | None = None,
        exam_session: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int, dict[str, list[Any]]]:
        return self.units.list_for_subject(
            self.subject.id,
            query=query,
            unit_code=unit_code,
            exam_year=exam_year,
            exam_session=exam_session,
            limit=limit,
            offset=offset,
        )

    def list_trash(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int, dict[str, list[Any]]]:
        return self.units.list_for_subject(
            self.subject.id,
            limit=limit,
            offset=offset,
            status="archived",
        )

    def get_unit(self, paper_unit_id: str) -> dict[str, Any]:
        unit = self.units.get(paper_unit_id, subject_id=self.subject.id)
        if unit is None:
            raise LookupError("试卷单元不存在")
        return unit

    def create_unit(
        self,
        document_ids: Sequence[str],
        *,
        display_name: str | None,
    ) -> dict[str, Any]:
        documents, identity = self._validate_documents(document_ids)
        pair_key = str(identity["pair_key"])
        active = self.units.find_by_pair(subject_id=self.subject.id, pair_key=pair_key)
        if active is not None:
            requested_ids = {str(document["id"]) for document in documents}
            active_ids = {str(document["id"]) for document in active["documents"]}
            if requested_ids == active_ids:
                return self.units.update(
                    str(active["id"]),
                    subject_id=self.subject.id,
                    display_name=self._normalize_display_name(display_name),
                    display_name_set=True,
                    documents=None,
                )
            raise ValueError("相同考试身份的试卷单元已存在，请在原单元中更新资料")
        archived = self.units.find_by_pair(
            subject_id=self.subject.id,
            pair_key=pair_key,
            status="archived",
        )
        if archived is not None:
            return self.units.restore(
                str(archived["id"]),
                subject_id=self.subject.id,
                display_name=self._normalize_display_name(display_name),
                documents=self._bindings(documents),
            )
        return self.units.create(
            subject_id=self.subject.id,
            subject_code=self.subject.subject_code,
            pair_key=pair_key,
            display_name=self._normalize_display_name(display_name),
            unit_code=str(identity["unit_code"]),
            exam_year=int(str(identity["exam_year"])),
            exam_session=str(identity["exam_session"]),
            documents=self._bindings(documents),
        )

    def update_unit(
        self,
        paper_unit_id: str,
        *,
        display_name: str | None,
        display_name_set: bool,
        document_ids: Sequence[str] | None,
    ) -> dict[str, Any]:
        unit = self.get_unit(paper_unit_id)
        bindings: list[dict[str, str]] | None = None
        if document_ids is not None:
            documents, _identity = self._validate_documents(
                document_ids,
                expected_pair_key=str(unit["pair_key"]),
            )
            bindings = self._bindings(documents)
        return self.units.update(
            paper_unit_id,
            subject_id=self.subject.id,
            display_name=self._normalize_display_name(display_name),
            display_name_set=display_name_set,
            documents=bindings,
        )

    def archive_unit(self, paper_unit_id: str) -> None:
        self.units.archive(paper_unit_id, subject_id=self.subject.id)

    def restore_unit(self, paper_unit_id: str) -> dict[str, Any]:
        return self.units.restore_archived(paper_unit_id, subject_id=self.subject.id)

    def permanently_delete_unit(self, paper_unit_id: str) -> None:
        self.units.permanently_delete(paper_unit_id, subject_id=self.subject.id)

    def answer_sources(
        self,
        paper_unit_id: str,
        *,
        question_paper_document_id: str,
        source_booklet_document_id: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        unit = self.get_unit(paper_unit_id)
        bound_roles = {str(document["id"]): str(document["role"]) for document in unit["documents"]}
        if bound_roles.get(question_paper_document_id) != "question_paper":
            raise ValueError("所选 Question Paper 不属于该试卷单元")
        paper = self._require_active_document(question_paper_document_id)
        booklet_id = source_booklet_document_id
        bound_booklets = [
            document_id for document_id, role in bound_roles.items() if role == "source_booklet"
        ]
        if booklet_id is None and self.subject.package.manifest.answering.requires_source_booklet:
            if len(bound_booklets) != 1:
                raise ValueError("该试卷必须明确选择一份配套 Source Booklet")
            booklet_id = bound_booklets[0]
        if booklet_id is None:
            return paper, None
        if bound_roles.get(booklet_id) != "source_booklet":
            raise ValueError("所选 Source Booklet 不属于该试卷单元")
        booklet = self._require_active_document(booklet_id)
        checksum = str(booklet.get("checksum") or "")
        if (
            booklet.get("status") != "converted"
            or not checksum
            or booklet.get("converted_source_checksum") != checksum
        ):
            raise ValueError("Source Booklet 尚未按当前文件版本完成转换")
        return paper, booklet

    def _validate_documents(
        self,
        document_ids: Sequence[str],
        *,
        expected_pair_key: str | None = None,
    ) -> tuple[list[dict[str, Any]], Mapping[str, object]]:
        unique_ids = tuple(dict.fromkeys(document_ids))
        if not unique_ids:
            raise ValueError("试卷单元至少需要一份 Question Paper")
        if len(unique_ids) != len(document_ids):
            raise ValueError("试卷单元不能重复关联同一份资料")
        documents = [self._require_active_document(document_id) for document_id in unique_ids]
        invalid_type = next(
            (
                str(document.get("source_type") or "")
                for document in documents
                if document.get("source_type") not in _ROLE_BY_SOURCE_TYPE
            ),
            None,
        )
        if invalid_type is not None:
            raise ValueError(f"{invalid_type or '未知类型'} 不能绑定到试卷单元")
        if not any(document.get("source_type") == "question_paper" for document in documents):
            raise ValueError("试卷单元至少需要一份 Question Paper")

        first = documents[0]
        pair_key = str(first.get("pair_key") or "")
        complete_identity = (
            first.get("identity_status") == "complete"
            and pair_key
            and first.get("unit_code") is not None
            and first.get("exam_year") is not None
            and first.get("exam_session") is not None
        )
        if not complete_identity:
            raise ValueError("资料缺少完整考试身份，不能加入试卷单元")
        if expected_pair_key is not None and pair_key != expected_pair_key:
            raise ValueError("资料与试卷单元的考试身份不一致")
        for document in documents[1:]:
            if (
                document.get("identity_status") != "complete"
                or str(document.get("pair_key") or "") != pair_key
                or document.get("unit_code") != first.get("unit_code")
                or document.get("exam_year") != first.get("exam_year")
                or document.get("exam_session") != first.get("exam_session")
            ):
                raise ValueError("所有资料必须具有完全一致的年份、考季和 Unit")
        return documents, first

    def _require_active_document(self, document_id: str) -> dict[str, Any]:
        document = self.documents.get_active(document_id)
        if document is None:
            raise LookupError("资料不存在或已删除")
        if document.get("subject_code") != self.subject.subject_code:
            raise LookupError("资料不属于当前科目")
        return document

    @staticmethod
    def _bindings(documents: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
        return [
            {
                "document_id": str(document["id"]),
                "role": _ROLE_BY_SOURCE_TYPE[str(document["source_type"])],
            }
            for document in documents
        ]

    @staticmethod
    def _normalize_display_name(display_name: str | None) -> str | None:
        if display_name is None:
            return None
        normalized = display_name.strip()
        if not normalized:
            return None
        if len(normalized) > 200:
            raise ValueError("试卷单元名称不能超过 200 个字符")
        return normalized
