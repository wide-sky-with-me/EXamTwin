from __future__ import annotations

import pytest
from examtwin.subjects.document_assignment import (
    resolve_document_assignment,
    resolve_document_assignment_after_file_validation,
    resolve_document_assignment_before_file_validation,
)

WORKSPACE = {
    "id": "workspace-1",
    "knowledge_bases": [
        {"id": "core-1", "kind": "core"},
        {"id": "supplementary-1", "kind": "supplementary"},
    ],
}


@pytest.mark.parametrize(
    ("source_type", "expected_authority"),
    [
        ("question_paper", "official"),
        ("insert", "official"),
        ("mark_scheme", "official"),
        ("examiner_report", "official"),
        ("answer_booklet", "supplementary"),
        ("specimen_paper", "supplementary"),
    ],
)
def test_assessment_source_cannot_enter_a_knowledge_base(
    source_type: str,
    expected_authority: str,
) -> None:
    assignment = resolve_document_assignment(
        WORKSPACE,
        source_type=source_type,
        knowledge_base_id="core-1",
        license_confirmed=False,
    )

    assert assignment.knowledge_base_id is None
    assert assignment.source_role == "assessment_only"
    assert assignment.authority_tier == expected_authority


@pytest.mark.parametrize(
    ("source_type", "expected_base", "expected_role", "expected_authority"),
    [
        ("syllabus", "core-1", "core_knowledge", "official"),
        ("slide", "supplementary-1", "supplementary_knowledge", "supplementary"),
    ],
)
def test_knowledge_source_defaults_to_the_matching_base(
    source_type: str,
    expected_base: str,
    expected_role: str,
    expected_authority: str,
) -> None:
    assignment = resolve_document_assignment(
        WORKSPACE,
        source_type=source_type,
        knowledge_base_id=None,
        license_confirmed=False,
    )

    assert assignment.knowledge_base_id == expected_base
    assert assignment.source_role == expected_role
    assert assignment.authority_tier == expected_authority


def test_licensed_textbook_assigned_to_core_is_licensed_core_knowledge() -> None:
    assignment = resolve_document_assignment(
        WORKSPACE,
        source_type="textbook",
        knowledge_base_id="core-1",
        license_confirmed=True,
    )

    assert assignment.knowledge_base_id == "core-1"
    assert assignment.source_role == "core_knowledge"
    assert assignment.authority_tier == "licensed_core"


def test_textbook_requires_license_confirmation() -> None:
    with pytest.raises(ValueError, match="教材必须确认已获授权"):
        resolve_document_assignment(
            WORKSPACE,
            source_type="textbook",
            knowledge_base_id="core-1",
            license_confirmed=False,
        )


def test_invalid_base_is_rejected_before_missing_textbook_authorization() -> None:
    with pytest.raises(ValueError) as error:
        resolve_document_assignment(
            WORKSPACE,
            source_type="textbook",
            knowledge_base_id="outside-workspace",
            license_confirmed=False,
        )

    assert str(error.value) == "知识库不存在于当前科目"


def test_core_base_rejects_supplementary_source() -> None:
    with pytest.raises(ValueError, match="核心知识库只接受考纲和已授权教材"):
        resolve_document_assignment(
            WORKSPACE,
            source_type="revision_note",
            knowledge_base_id="core-1",
            license_confirmed=False,
        )


def test_other_base_rejection_is_deferred_until_after_file_validation() -> None:
    assignment = resolve_document_assignment_before_file_validation(
        WORKSPACE,
        source_type="other",
        knowledge_base_id="core-1",
        license_confirmed=False,
    )

    assert assignment is None
    with pytest.raises(ValueError) as error:
        resolve_document_assignment_after_file_validation(
            assignment,
            source_type="other",
            knowledge_base_id="core-1",
        )

    assert str(error.value) == "未分类资料不能进入知识库"


def test_direct_assignment_resolution_preserves_other_base_rejection() -> None:
    with pytest.raises(ValueError) as error:
        resolve_document_assignment(
            WORKSPACE,
            source_type="other",
            knowledge_base_id="core-1",
            license_confirmed=False,
        )

    assert str(error.value) == "未分类资料不能进入知识库"
