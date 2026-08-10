from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

KNOWLEDGE_SOURCE_TYPES = frozenset(
    {"syllabus", "textbook", "slide", "revision_note", "topic_practice"}
)
ASSESSMENT_SOURCE_TYPES = frozenset(
    {
        "question_paper",
        "insert",
        "mark_scheme",
        "examiner_report",
        "answer_booklet",
        "specimen_paper",
    }
)


@dataclass(frozen=True)
class DocumentAssignment:
    knowledge_base_id: str | None
    source_role: str
    authority_tier: str


def validate_document_source_type(source_type: str) -> None:
    if source_type not in KNOWLEDGE_SOURCE_TYPES | ASSESSMENT_SOURCE_TYPES | {"other"}:
        raise ValueError("未知资料类型")


def resolve_document_assignment_before_file_validation(
    workspace: Mapping[str, object],
    *,
    source_type: str,
    knowledge_base_id: str | None,
    license_confirmed: bool,
) -> DocumentAssignment | None:
    """Resolve rules that historically precede validation of uploaded bytes."""
    validate_document_source_type(source_type)
    if source_type == "other":
        return None
    return _resolve_known_document_assignment(
        workspace,
        source_type=source_type,
        knowledge_base_id=knowledge_base_id,
        license_confirmed=license_confirmed,
    )


def resolve_document_assignment_after_file_validation(
    assignment: DocumentAssignment | None,
    *,
    source_type: str,
    knowledge_base_id: str | None,
) -> DocumentAssignment:
    """Finish rules that historically follow validation of uploaded bytes."""
    if assignment is not None:
        return assignment
    if source_type != "other":
        raise RuntimeError("资料归属校验阶段不完整")
    if knowledge_base_id is not None:
        raise ValueError("未分类资料不能进入知识库")
    return DocumentAssignment(
        knowledge_base_id=None,
        source_role="excluded",
        authority_tier="supplementary",
    )


def resolve_document_assignment(
    workspace: Mapping[str, object],
    *,
    source_type: str,
    knowledge_base_id: str | None,
    license_confirmed: bool,
) -> DocumentAssignment:
    assignment = resolve_document_assignment_before_file_validation(
        workspace,
        source_type=source_type,
        knowledge_base_id=knowledge_base_id,
        license_confirmed=license_confirmed,
    )
    return resolve_document_assignment_after_file_validation(
        assignment,
        source_type=source_type,
        knowledge_base_id=knowledge_base_id,
    )


def _resolve_known_document_assignment(
    workspace: Mapping[str, object],
    *,
    source_type: str,
    knowledge_base_id: str | None,
    license_confirmed: bool,
) -> DocumentAssignment:
    if source_type in ASSESSMENT_SOURCE_TYPES:
        authority_tier = (
            "official"
            if source_type in {"question_paper", "insert", "mark_scheme", "examiner_report"}
            else "supplementary"
        )
        return DocumentAssignment(
            knowledge_base_id=None,
            source_role="assessment_only",
            authority_tier=authority_tier,
        )

    raw_bases = workspace.get("knowledge_bases", [])
    bases = (
        [base for base in raw_bases if isinstance(base, Mapping)]
        if isinstance(raw_bases, list)
        else []
    )
    selected_id = knowledge_base_id
    if selected_id is None:
        expected_kind = "core" if source_type in {"syllabus", "textbook"} else "supplementary"
        selected_id = next(
            (str(base["id"]) for base in bases if base.get("kind") == expected_kind),
            None,
        )
    selected_base = next(
        (base for base in bases if str(base.get("id")) == selected_id),
        None,
    )
    if selected_base is None:
        raise ValueError("知识库不存在于当前科目")
    if source_type == "textbook" and not license_confirmed:
        raise ValueError("教材必须确认已获授权后才能进入知识库")

    base_kind = str(selected_base.get("kind"))
    if base_kind == "core":
        if source_type not in {"syllabus", "textbook"}:
            raise ValueError("核心知识库只接受考纲和已授权教材")
        source_role = "core_knowledge"
    else:
        if source_type == "syllabus":
            raise ValueError("考纲必须归属核心知识库")
        source_role = "supplementary_knowledge"

    authority_tier = (
        "official"
        if source_type == "syllabus"
        else "licensed_core"
        if source_type == "textbook"
        else "supplementary"
    )
    return DocumentAssignment(
        knowledge_base_id=selected_id,
        source_role=source_role,
        authority_tier=authority_tier,
    )
