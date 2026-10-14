from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from examtwin.assessment.paper_question_candidates import (
    _apply_question_repair_plan,
    _merge_split_questions,
    _QuestionCandidateConflict,
    _QuestionRepairPlan,
)
from pydantic import ValidationError


@pytest.mark.parametrize("indexes", [[0], [0, 0], [0, 2], [-1, 1]])
def test_repair_plan_uses_every_candidate_exactly_once(indexes: list[int]) -> None:
    items = [
        {"number": "1", "question_markdown": "Find x."},
        {"number": "1", "question_markdown": "Find y."},
    ]
    plan = _QuestionRepairPlan.model_validate(
        {"groups": [{"number": "1", "candidate_indexes": indexes}]}
    )

    with pytest.raises(ValueError, match="恰好使用一次"):
        _apply_question_repair_plan(items, plan)


@pytest.mark.parametrize("level", ["plan", "group"])
def test_repair_plan_rejects_unknown_fields(level: str) -> None:
    payload: dict[str, Any] = {"groups": [{"number": "1", "candidate_indexes": [0]}]}
    target = payload if level == "plan" else payload["groups"][0]
    target["unexpected"] = "must not be silently dropped"

    with pytest.raises(ValidationError, match="extra_forbidden"):
        _QuestionRepairPlan.model_validate(payload)


@pytest.mark.parametrize(
    ("numbers", "groups", "error"),
    [
        (
            ["1", "01"],
            [
                {"number": "1", "candidate_indexes": [0]},
                {"number": "01", "candidate_indexes": [1]},
            ],
            "重复或无效的顶层题号",
        ),
        (
            ["1", "1"],
            [{"number": "1", "candidate_indexes": [0, 1]}],
            "选择权威候选",
        ),
        (
            ["1", "2"],
            [
                {"number": "1", "candidate_indexes": [0], "preferred_candidate_index": 1},
                {"number": "2", "candidate_indexes": [1]},
            ],
            "组外候选",
        ),
        (
            ["1"],
            [{"number": "2", "candidate_indexes": [0]}],
            "无来源题号",
        ),
        (
            ["1", "1(a)"],
            [{"number": "1", "candidate_indexes": [0, 1], "preferred_candidate_index": 1}],
            "不匹配的权威候选",
        ),
        (
            ["1", "2"],
            [{"number": "1", "candidate_indexes": [0, 1], "preferred_candidate_index": 1}],
            "不匹配的权威候选",
        ),
    ],
)
def test_repair_plan_preserves_number_family_and_authority_gates(
    numbers: list[str], groups: list[dict[str, Any]], error: str
) -> None:
    items = [{"number": number, "question_markdown": "Find x."} for number in numbers]
    plan = _QuestionRepairPlan.model_validate({"groups": groups})

    with pytest.raises(ValueError, match=error):
        _apply_question_repair_plan(items, plan)


def test_repair_plan_preserves_selected_wording_and_only_fills_empty_requirements() -> None:
    items = [
        {
            "number": "1",
            "question_markdown": "Untrusted alternative wording.",
            "source_pages": [99],
            "total_marks": 20,
            "requires_visual_context": True,
            "answer_requirements": [
                {"label": "whole", "marks": 20},
                {"label": "1(a)", "marks": 9, "answer_kind": "text", "units": ["m"]},
                {"label": "(b)", "marks": 11},
            ],
            "knowledge_codes": ["shared", "alternative"],
            "_split_source": "recovery",
        },
        {
            "number": "01",
            "question_markdown": "(a) Find the speed. [2 marks]",
            "source_pages": [2],
            "total_marks": 2,
            "requires_visual_context": False,
            "answer_requirements": [
                {"label": "(a)", "marks": 2, "answer_kind": "numeric", "units": []}
            ],
            "knowledge_codes": ["selected", "shared"],
            "_split_source": "primary",
            "_split_source_digest": "primary-source",
            "_split_batch_index": 2,
        },
    ]
    before = deepcopy(items)
    plan = _QuestionRepairPlan.model_validate(
        {"groups": [{"number": "1", "candidate_indexes": [0, 1], "preferred_candidate_index": 1}]}
    )

    [repaired] = _apply_question_repair_plan(items, plan)

    assert repaired == {
        "number": "1",
        "question_markdown": "(a) Find the speed. [2 marks]",
        "total_marks": None,
        "requires_visual_context": True,
        "answer_requirements": [
            {"label": "(a)", "marks": 2, "answer_kind": "numeric", "units": ["m"]}
        ],
        "knowledge_codes": ["selected", "shared", "alternative"],
    }
    assert items == before


def test_repair_plan_follows_group_order_and_defers_source_page_reconciliation() -> None:
    items = [
        {"number": "2", "question_markdown": "Second question.", "source_pages": [99]},
        {"number": "1", "question_markdown": "First question.", "source_pages": [98]},
    ]
    before = deepcopy(items)
    plan = _QuestionRepairPlan.model_validate(
        {
            "groups": [
                {"number": "1", "candidate_indexes": [1]},
                {"number": "02", "candidate_indexes": [0]},
            ]
        }
    )

    repaired = _apply_question_repair_plan(items, plan)

    assert repaired == [
        {"number": "1", "question_markdown": "First question.", "requires_visual_context": False},
        {"number": "02", "question_markdown": "Second question.", "requires_visual_context": False},
    ]
    assert items == before


def test_merge_rejects_cross_primary_source_digests_even_with_identical_wording() -> None:
    items = [
        {"number": "1", "question_markdown": "Find x.", "_split_source_digest": digest}
        for digest in ("source-a", "source-b")
    ]

    with pytest.raises(ValueError, match="禁止跨来源合并"):
        _merge_split_questions(items)


def test_merge_conflict_carries_question_number_for_targeted_service_repair() -> None:
    items = [
        {"number": "02", "question_markdown": "Find x."},
        {"number": "2", "question_markdown": "Find y."},
    ]

    with pytest.raises(_QuestionCandidateConflict, match="题干冲突") as raised:
        _merge_split_questions(items)

    assert raised.value.question_numbers == ("02",)
    assert isinstance(raised.value.__cause__, _QuestionCandidateConflict)


@pytest.mark.parametrize("source", ["primary", "recovery"])
def test_merge_strips_batch_provenance_before_service_reconciliation(source: str) -> None:
    item = {
        "number": "1",
        "question_markdown": "Find x.",
        "source_pages": [99],
        "_split_source": source,
        "_split_source_digest": "source",
        "_split_batch_index": 0,
    }
    before = deepcopy(item)

    assert _merge_split_questions([item]) == [{"number": "1", "question_markdown": "Find x."}]
    assert item == before


@pytest.mark.parametrize("marks", [None, True])
def test_merge_does_not_treat_unknown_or_boolean_marks_as_numeric(marks: object) -> None:
    items = [
        {
            "number": "1",
            "question_markdown": "(a) Find x.\n(b) Find y.",
            "answer_requirements": [
                {"label": "(a)", "marks": 2},
                {"label": "(b)", "marks": marks},
            ],
        }
    ]

    [merged] = _merge_split_questions(items)

    assert merged["total_marks"] is None
    assert merged["answer_requirements"] == items[0]["answer_requirements"]
