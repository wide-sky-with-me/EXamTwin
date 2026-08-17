from __future__ import annotations

import json
import re
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest
from examtwin.assessment.answering_agent.contracts import QuestionImage
from examtwin.assessment.paper_answering import (
    PaperAnswerService,
    _align_primary_question_numbers_from_recovery,
    _drop_covered_recovery_fragments,
    _merge_split_questions,
    _split_markdown_batches,
)
from examtwin.assessment.paper_parsing import (
    question_has_unresolved_source_placeholder,
    question_requires_visual_context,
    question_source_structures,
    reconcile_question_source_pages,
    upload_to_markdown,
    validate_question_source_structure,
)
from examtwin.assessment.paper_vision import format_physical_page_markdown
from examtwin.contracts import AskResponse, Citation
from examtwin.platform.config import Settings
from examtwin.subjects.public import subject_context


def fake_catalog(_unit_code: str | None) -> list[dict[str, Any]]:
    return [
        {
            "id": "9660:P2.7.O03",
            "code": "P2.7.O03",
            "title": "Integration by parts.",
            "source_ref": "spec.pdf#page=22",
            "difficulty_score": 0.72,
            "difficulty_label": "hard",
            "difficulty_confidence": 0.3,
            "evidence_level": "D",
            "references": [],
            "features": {
                "node_type": "learning_objective",
                "description": "Reverse of the product rule.",
            },
        }
    ]


def test_primary_question_number_uses_unique_near_identical_recovery_witness() -> None:
    question = (
        "According to the Prebisch-Singer hypothesis, explain how a buffer stock stabilises "
        "commodity prices and calculate the resulting percentage change in export volume. "
        "Show every step and give the final answer to the nearest whole percentage point."
    )
    candidates = [
        {
            "number": "1",
            "question_markdown": (
                "Which combination of policies is most likely to promote long-run development? "
                "Select one answer and explain why the remaining policy combination is unsuitable."
            ),
            "total_marks": 10,
            "_split_source": "primary",
        },
        {
            "number": "1",
            "question_markdown": question,
            "total_marks": 10,
            "_split_source": "primary",
        },
        {
            "number": "11",
            "question_markdown": question.replace("stabilises", "stabilizes"),
            "total_marks": 10,
            "_split_source": "recovery",
        },
        {"number": "10", "question_markdown": "Previous question.", "_split_source": "primary"},
        {"number": "12", "question_markdown": "Following question.", "_split_source": "primary"},
    ]

    aligned = _align_primary_question_numbers_from_recovery(candidates)

    assert aligned[0]["number"] == "1"
    assert aligned[1]["number"] == "11"
    assert aligned[1]["question_markdown"] == question
    assert candidates[1]["number"] == "1"


def test_recovery_number_cannot_override_coherent_primary_sequence() -> None:
    question = "Evaluate whether monetary policy can support economic growth and development. " * 4
    candidates = [
        {"number": "13", "question_markdown": "Previous question.", "_split_source": "primary"},
        {
            "number": "14",
            "question_markdown": question,
            "total_marks": 25,
            "_split_source": "primary",
        },
        {"number": "15", "question_markdown": "Following question.", "_split_source": "primary"},
        {
            "number": "24",
            "question_markdown": question,
            "total_marks": 25,
            "_split_source": "recovery",
        },
    ]

    aligned = _align_primary_question_numbers_from_recovery(candidates)

    assert aligned[1]["number"] == "14"


def test_primary_number_accepts_long_partial_recovery_witness_across_batch_boundary() -> None:
    shared = (
        "According to the Prebisch-Singer hypothesis, primary commodities and manufactured "
        "goods have different income elasticities of demand. Explain how a buffer stock is "
        "used to stabilise the price of a primary commodity and use the supplied table to "
        "calculate the change in export volumes. "
    ) * 3
    primary = shared + (
        "Finally, assess whether this price instability constrains economic development."
    )
    recovery = shared.replace("stabilise", "stabilize")
    candidates = [
        {"number": "10", "question_markdown": "Previous question.", "_split_source": "primary"},
        {
            "number": "1",
            "question_markdown": "A distinct multiple-choice question about development policy. "
            * 4,
            "total_marks": 1,
            "_split_source": "primary",
        },
        {
            "number": "1",
            "question_markdown": primary,
            "total_marks": 10,
            "_split_source": "primary",
        },
        {
            "number": "11",
            "question_markdown": recovery,
            "total_marks": 4,
            "_split_source": "recovery",
        },
        {"number": "12", "question_markdown": "Following question.", "_split_source": "primary"},
    ]

    aligned = _align_primary_question_numbers_from_recovery(candidates)

    assert aligned[2]["number"] == "11"
    assert aligned[2]["question_markdown"] == primary


@pytest.mark.parametrize(
    "recovery_candidates",
    [
        [
            {
                "number": "11",
                "question_markdown": "A short repeated instruction.",
                "total_marks": 2,
                "_split_source": "recovery",
            }
        ],
        [
            {
                "number": number,
                "question_markdown": "Explain the same long economic scenario in full. " * 6,
                "total_marks": 10,
                "_split_source": "recovery",
            }
            for number in ("11", "12")
        ],
    ],
)
def test_primary_question_number_alias_fails_closed_without_unique_strong_proof(
    recovery_candidates: list[dict[str, Any]],
) -> None:
    primary_text = (
        "A short repeated instruction."
        if len(recovery_candidates) == 1
        else "Explain the same long economic scenario in full. " * 6
    )
    candidates = [
        {
            "number": "1",
            "question_markdown": primary_text,
            "total_marks": 10 if len(recovery_candidates) > 1 else 2,
            "_split_source": "primary",
        },
        *recovery_candidates,
    ]

    aligned = _align_primary_question_numbers_from_recovery(candidates)

    assert aligned[0]["number"] == "1"


def test_recovery_decimal_fragments_already_covered_by_primary_are_dropped() -> None:
    primary = {
        "number": "12",
        "question_markdown": (
            "Extract A shows labour-force and real-GDP growth.\n\n"
            "**12.1** Explain why labour-force growth is likely to affect a country's real "
            "GDP and use the supplied data to support the transmission mechanism. "
            "**[4 marks]**\n\n"
            "**12.2** Assess the relationship shown by the data. **[4 marks]**"
        ),
        "total_marks": 8,
        "_split_source": "primary",
    }
    covered_recovery = {
        "number": "121",
        "question_markdown": (
            "Extract A shows labour-force and real-GDP growth. Explain why labour-force growth "
            "is likely to affect a country's real GDP and use the supplied data to support the "
            "transmission mechanism. [4 marks]"
        ),
        "total_marks": 4,
        "_split_source": "recovery",
    }
    unrelated_recovery = {
        "number": "131",
        "question_markdown": (
            "Evaluate a genuinely absent question about exchange-rate policy and economic "
            "development using the evidence supplied in Extract C. "
        )
        * 2,
        "total_marks": 12,
        "_split_source": "recovery",
    }

    retained = _drop_covered_recovery_fragments([primary, covered_recovery, unrelated_recovery])

    assert covered_recovery not in retained
    assert retained == [primary, unrelated_recovery]


def test_long_paper_split_batches_preserve_the_tail_without_silent_truncation() -> None:
    sections = [
        f"<!-- examtwin:physical-page={page} -->\nQuestion {page}\n" + ("x" * 700)
        for page in range(1, 9)
    ]
    markdown = "".join(sections)

    batches = _split_markdown_batches(markdown, max_chars=2_000)

    assert len(batches) > 1
    assert "Question 1" in batches[0]
    assert "Question 8" in batches[-1]
    assert all(len(batch) <= 3_000 for batch in batches)


def test_split_batches_are_concurrent_and_resume_from_digest_checkpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    markdown = "".join(
        f"<!-- examtwin:physical-page={number} -->\n"
        f"{number} Find the value of x. [2 marks]\n" + ("working space\n" * 280)
        for number in range(1, 5)
    )
    settings = Settings(paper_split_max_chars=6_000, paper_split_concurrency=2)
    active = 0
    max_active = 0
    failed_once = False
    calls = 0
    guard = threading.Lock()

    class FakeLLM:
        def complete(self, prompt: str) -> SimpleNamespace:
            nonlocal active, calls, failed_once, max_active
            with guard:
                active += 1
                calls += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.03)
                if "3 Find the value" in prompt and not failed_once:
                    failed_once = True
                    raise TimeoutError("one split batch timed out")
                numbers = sorted(set(re.findall(r"(?m)^(\d+) Find the value", prompt)))
                return SimpleNamespace(
                    text=json.dumps(
                        {
                            "questions": [
                                {
                                    "number": number,
                                    "question_markdown": (
                                        f"{number} Find the value of x. [2 marks]"
                                    ),
                                    "source_pages": [int(number)],
                                    "requires_visual_context": False,
                                    "total_marks": 2,
                                    "answer_requirements": [
                                        {
                                            "label": "whole",
                                            "marks": 2,
                                            "answer_kind": "numeric",
                                            "units": [],
                                            "required_tool": None,
                                        }
                                    ],
                                    "knowledge_codes": [],
                                }
                                for number in numbers
                            ]
                        }
                    )
                )
            finally:
                with guard:
                    active -= 1

    monkeypatch.setattr(
        "examtwin.assessment.paper_answering.build_llm",
        lambda *_args, **_kwargs: FakeLLM(),
    )
    checkpoints: dict[tuple[int, str], list[dict[str, Any]]] = {}

    def load(batch_index: int, digest: str) -> list[dict[str, Any]] | None:
        return checkpoints.get((batch_index, digest))

    def save(
        batch_index: int,
        _batch_count: int,
        digest: str,
        questions: list[dict[str, Any]],
        _duration_ms: float,
    ) -> None:
        checkpoints[(batch_index, digest)] = questions

    service = PaperAnswerService(
        settings,
        subject_context(settings),
        catalog_loader=fake_catalog,
        rag=object(),
    )
    with pytest.raises(TimeoutError, match="one split batch"):
        service.split_questions_checkpointed(
            markdown,
            unit_code="P2",
            load_checkpoint=load,
            save_checkpoint=save,
        )

    completed_before_retry = len(checkpoints)
    calls_before_retry = calls
    result = service.split_questions_checkpointed(
        markdown,
        unit_code="P2",
        load_checkpoint=load,
        save_checkpoint=save,
    )

    batch_count = len(_split_markdown_batches(markdown, max_chars=6_000))
    assert max_active == 2
    assert completed_before_retry > 0
    assert calls - calls_before_retry == batch_count - completed_before_retry
    assert [item["number"] for item in result] == ["1", "2", "3", "4"]


def test_split_batch_retries_malformed_json_before_failing_the_paper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    markdown = format_physical_page_markdown([(1, "1 Find x. [2 marks]")])
    calls = 0

    class FakeLLM:
        def complete(self, prompt: str) -> SimpleNamespace:
            nonlocal calls
            calls += 1
            if calls == 1:
                return SimpleNamespace(text='{"questions" [{"number": "1"}]}')
            assert "previous response was not valid JSON" in prompt
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "questions": [
                            {
                                "number": "1",
                                "question_markdown": "1 Find x. [2 marks]",
                                "source_pages": [1],
                                "requires_visual_context": False,
                                "total_marks": 2,
                                "answer_requirements": [
                                    {
                                        "label": "whole",
                                        "marks": 2,
                                        "answer_kind": "numeric",
                                        "units": [],
                                        "required_tool": None,
                                    }
                                ],
                            }
                        ]
                    }
                )
            )

    monkeypatch.setattr(
        "examtwin.assessment.paper_answering.build_llm",
        lambda *_args, **_kwargs: FakeLLM(),
    )
    settings = Settings(paper_split_max_attempts=2)
    service = PaperAnswerService(
        settings,
        subject_context(settings),
        catalog_loader=fake_catalog,
        rag=object(),
    )

    [question] = service.split_questions(markdown, unit_code="P2")

    assert calls == 2
    assert question["number"] == "1"
    assert question["source_pages"] == [1]


def test_split_recovery_appendix_does_not_duplicate_source_page_provenance() -> None:
    primary = format_physical_page_markdown(
        [(1, "1 Find x. [2 marks]"), (2, "2 Find y. [2 marks]")]
    )
    recovery = format_physical_page_markdown([(1, "1 Find x."), (2, "2 Find y.")])
    settings = Settings()
    service = PaperAnswerService(
        settings,
        subject_context(settings),
        splitter=lambda _markdown, _catalog: [
            {"number": "1", "question_markdown": "1 Find x. [2 marks]"},
            {"number": "2", "question_markdown": "2 Find y. [2 marks]"},
        ],
        catalog_loader=fake_catalog,
        rag=object(),
    )

    result = service.split_questions_checkpointed(
        f"{primary}\n\n{recovery}",
        source_markdown=primary,
        unit_code="P2",
        load_checkpoint=lambda _index, _digest: None,
        save_checkpoint=lambda _index, _count, _digest, _items, _duration: None,
    )

    assert [item["source_pages"] for item in result] == [[1], [2]]


def test_split_merge_collapses_recovery_number_variants_before_source_reconciliation() -> None:
    primary = [
        {
            "number": "01",
            "question_markdown": "Which option describes the price mechanism?",
        },
        {
            "number": "17",
            "question_markdown": (
                "(a) Calculate the income index. (b) Calculate the median payment. [4 marks]"
            ),
        },
    ]
    recovery = [
        {
            "number": "1",
            "question_markdown": "Which option describes the price mechanism? [1 mark]",
        },
        {"number": "17.1", "question_markdown": "Calculate the income index."},
        {"number": "17.2", "question_markdown": "Calculate the median payment."},
    ]
    source_markdown = format_physical_page_markdown(
        [
            (1, "01 Which option describes the price mechanism? [1 mark]"),
            (
                2,
                "17 (a) Calculate the income index. "
                "(b) Calculate the median payment. [4 marks]\nEND OF QUESTIONS",
            ),
        ]
    )

    merged = _merge_split_questions([*primary, *recovery])
    reconciled = reconcile_question_source_pages(source_markdown, merged)

    assert [item["number"] for item in reconciled] == ["01", "17"]
    assert [item["source_pages"] for item in reconciled] == [[1], [2]]
    assert "(b) Calculate the median payment." in reconciled[1]["question_markdown"]


def test_split_merge_preserves_primary_stem_and_repairs_cross_batch_subparts() -> None:
    primary_stem = {
        "number": "8",
        "question_markdown": (
            "The continuous random variable $X$ has cumulative distribution function\n"
            "$$F(x)=\\begin{cases}0,&x<1\\\\"
            "\\dfrac{2x^3+3x}{90}+g,&1\\le x<3\\\\"
            "\\dfrac{207x-25x^2-338}{h},&3\\le x<4\\\\"
            "1,&x\\ge4\\end{cases}$$\n\n"
            "(a) Find $h$. [2 marks]\n\n"
            "(b) Find $g$. [2 marks]\n\n"
            "(c) Find $f(x)$. [3 marks]"
        ),
        "answer_requirements": [
            {"label": "(a)", "marks": 2, "answer_kind": "numeric"},
            {"label": "(b)", "marks": 2, "answer_kind": "numeric"},
            {"label": "(c)", "marks": 3, "answer_kind": "expression"},
        ],
        "_split_source": "primary",
        "_split_batch_index": 1,
    }
    primary_continuation = {
        "number": "8",
        "question_markdown": (
            "(c) Find $f(x)$. [3 marks]\n\n"
            "(d) Find the exact value of $E(1/X)$. "
            "Give your answer in the form "
            "$p\\ln3+q\\ln4-\\dfrac{13}{45}$. [7 marks]"
        ),
        "answer_requirements": [
            {"label": "(c)", "marks": 3, "answer_kind": "expression"},
            {"label": "(d)", "marks": 7, "answer_kind": "expression"},
        ],
        "_split_source": "primary",
        "_split_batch_index": 2,
    }
    recovery = {
        "number": "8",
        "question_markdown": (
            "The continuous random variable $X$ has cumulative distribution function\n"
            "$$F(x)=\\begin{cases}\\text{[piecewise definition as printed]},"
            "&\\text{[ranges as printed]}\\end{cases}$$\n\n"
            "(a) Find $h$. [2 marks]\n\n"
            "(b) Find $g$. [2 marks]\n\n"
            "(c) Find $f(x)$. [3 marks]\n\n"
            "(d) Find the exact value of $E(1/X)$. [7 marks]"
        ),
        "answer_requirements": [
            {"label": "(a)", "marks": 2, "answer_kind": "numeric"},
            {"label": "(b)", "marks": 2, "answer_kind": "numeric"},
            {"label": "(c)", "marks": 3, "answer_kind": "expression"},
            {"label": "(d)", "marks": 7, "answer_kind": "expression"},
        ],
        "_split_source": "recovery",
        "_split_batch_index": 5,
    }

    [merged] = _merge_split_questions([primary_stem, primary_continuation, recovery])

    assert "\\dfrac{207x-25x^2-338}{h}" in merged["question_markdown"]
    assert "p\\ln3+q\\ln4-\\dfrac{13}{45}" in merged["question_markdown"]
    assert merged["question_markdown"].count("(c)") == 1
    assert "piecewise definition as printed" not in merged["question_markdown"]
    assert [part["label"] for part in merged["answer_requirements"]] == [
        "(a)",
        "(b)",
        "(c)",
        "(d)",
    ]
    assert merged["total_marks"] == 14
    assert not any(key.startswith("_split_") for key in merged)


def test_source_structure_reads_subparts_prefixed_by_question_number() -> None:
    source = format_physical_page_markdown(
        [
            (
                2,
                "## 1\n\nA stem.\n\n"
                "### 1 (a)\n\nFor this part, use the given information.\n\n"
                "### 1 (a) (i)\n\nState a value. \\([1\\text{ mark}]\\)\n\n"
                "### 1 (a) (ii)\n\nFind a value. \\[3 marks\\]\n\n"
                "## 1 (b)\n\nFind another value. [3 marks]\n\nEND OF QUESTIONS",
            )
        ]
    )

    [structure] = question_source_structures(source)

    assert structure.subpart_labels == ("(a)(i)", "(a)(ii)", "(b)")
    assert structure.marks == (1, 3, 3)


def test_source_structure_does_not_promote_letter_subpart_or_leak_next_stem() -> None:
    source = format_physical_page_markdown(
        [
            (3, "## 2\n\nDescribe two transformations. [4 marks]"),
            (
                4,
                "Turn over for the next question\n\n"
                "## 3\n\nThe functions $f$ and $g$ are defined below.\n\n"
                "### 3 (a)\n\nFind the range of $f$. [2 marks]",
            ),
            (5, "### 3 (b)\n\nFind $f^{-1}(x)$. [3 marks]"),
        ]
    )

    structures = question_source_structures(source)

    assert [structure.number for structure in structures] == ["2", "3"]
    assert "functions $f$ and $g$" not in structures[0].question_markdown
    assert structures[1].question_markdown.startswith(
        "The functions $f$ and $g$ are defined below."
    )
    assert "### 3 (a)" in structures[1].question_markdown
    assert structures[1].subpart_labels == ("(a)", "(b)")


def test_source_structure_keeps_marked_subpart_before_turn_over_instruction() -> None:
    source = format_physical_page_markdown(
        [
            (
                6,
                "## 4\n\nA pair of lines intersect.\n\n"
                "**4 (a)** Find the value of $p$. **[5 marks]**",
            ),
            (
                7,
                "**4 (b)** Find the value of $q$. **[3 marks]**\n\nTurn over for the next question",
            ),
            (8, "## 5\n\nFind the polynomial. **[4 marks]**"),
        ]
    )

    structures = question_source_structures(source)

    assert [structure.number for structure in structures] == ["4", "5"]
    assert structures[0].subpart_labels == ("(a)", "(b)")
    assert structures[0].marks == (5, 3)
    assert structures[0].source_pages == (6, 7)


def test_source_structure_accepts_unicode_space_after_subpart_label() -> None:
    source = format_physical_page_markdown(
        [
            (
                6,
                "## 4\n\nA pair of lines intersect.\n\n4 (a)\u2003Find the value of $p$. [5 marks]",
            ),
            (7, "## 4 (b)\n\nFind the value of $q$. [3 marks]"),
        ]
    )

    [structure] = question_source_structures(source)

    assert structure.subpart_labels == ("(a)", "(b)")
    assert structure.marks == (5, 3)


def test_source_structure_repairs_dropped_leading_digit_with_adjacent_subpart_proof() -> None:
    source = format_physical_page_markdown(
        [
            (2, "## 01\n\nChoose one answer. **[1 mark]**"),
            (9, "## 10\n\nChoose another answer. **[1 mark]**"),
            (
                10,
                "## Section B\n\n### 1\n\nA commodity-price scenario.\n\n"
                "#### 1.1\n\nState two uses. **[2 marks]**\n\n"
                "#### 1.2\n\nCalculate the change. **[2 marks]**",
            ),
            (11, "### 11.3\n\nExplain the effect. **[6 marks]**"),
            (
                12,
                "**Section C**\n\nAnswer all questions.\n\n**12** Use Extract A. **[4 marks]**",
            ),
        ]
    )

    structures = question_source_structures(source)

    assert [structure.number for structure in structures] == ["1", "10", "11", "12"]
    assert structures[2].subpart_labels == (".1", ".2", ".3")
    assert structures[2].marks == (2, 2, 6)
    assert structures[2].source_pages == (10, 11)
    assert "### 11.1" in structures[2].question_markdown
    assert "### 11.2" in structures[2].question_markdown


def test_source_structure_repairs_redundant_decimal_prefix_sequence() -> None:
    source = format_physical_page_markdown(
        [
            (
                10,
                "**11** Commodity prices are unstable.\n\n"
                "**11.1.1** State two buffer-stock operations. **[2 marks]**\n\n"
                "**11.1.2** Calculate the percentage difference. **[2 marks]**",
            ),
            (
                11,
                "**11.3** Explain the effect using a demand and supply diagram. **[6 marks]**",
            ),
        ]
    )
    questions = [
        {
            "number": "11",
            "question_markdown": "Complete question 11.",
            "answer_requirements": [
                {"label": "**11.1.1**", "marks": 2, "answer_kind": "text"},
                {"label": "**11.1.2**", "marks": 2, "answer_kind": "numeric"},
                {
                    "label": "**11.3**",
                    "marks": 6,
                    "answer_kind": "economics_diagram",
                },
            ],
            "total_marks": 10,
        }
    ]

    [structure] = question_source_structures(source)
    [validated] = validate_question_source_structure(source, questions)

    assert structure.subpart_labels == (".1", ".2", ".3")
    assert "**11.1**" in structure.question_markdown
    assert "**11.2**" in structure.question_markdown
    assert [part["label"] for part in validated["answer_requirements"]] == [
        ".1",
        ".2",
        ".3",
    ]


def test_source_structure_normalizes_escaped_breaks_and_stops_at_paper_end() -> None:
    source = format_physical_page_markdown(
        [
            (
                10,
                "## 5\n\nA stem.\n\n"
                "### 5 (a)\n\nFind a. [2 marks]\n\n"
                "### 5 (b)\n\nFind b. [2 marks]",
            ),
            (
                11,
                "5 (c) Find c.\\n\\n[2 marks]\\n\\n"
                "5 (d) Find d.\\n\\n[3 marks]\\n\\nEND OF QUESTIONS",
            ),
            (12, "There are no questions printed on this page."),
        ]
    )

    [structure] = question_source_structures(source)

    assert structure.subpart_labels == ("(a)", "(b)", "(c)", "(d)")
    assert structure.marks == (2, 2, 2, 3)
    assert structure.source_pages == (10, 11)


def test_source_structure_stops_before_next_section_selection_panel() -> None:
    source = format_physical_page_markdown(
        [
            (
                16,
                "## 14\n\nAssess the contribution of monetary policy. [25 marks]",
            ),
            (
                19,
                "## Section D\n\nAnswer **EITHER** Question 15 **OR** Question 16.\n\n"
                "Shade the circle below to indicate your choice.\n\n"
                "Question 15\n\nQuestion 16\n\n"
                "## 15\n\nAssess the benefits of trade. [25 marks]\n\n"
                "## 16\n\nAssess the effects of globalisation. [25 marks]",
            ),
        ]
    )

    structures = question_source_structures(source)

    assert [structure.number for structure in structures] == ["14", "15", "16"]
    assert structures[0].question_markdown == (
        "Assess the contribution of monetary policy. [25 marks]"
    )
    assert structures[0].source_pages == (16,)
    assert structures[0].requires_visual_context is False


def test_source_structure_stops_last_question_before_additional_page() -> None:
    source = format_physical_page_markdown(
        [
            (19, "## 16\n\nAssess the effects of globalisation. [25 marks]"),
            (20, ""),
            (
                24,
                "Question number\nAdditional page, if required.\n"
                "Write the question numbers in the left-hand margin.",
            ),
            (25, ""),
        ]
    )

    [structure] = question_source_structures(source)

    assert structure.question_markdown == "Assess the effects of globalisation. [25 marks]"
    assert structure.source_pages == (19,)


def test_source_structure_ignores_clock_header_before_question_eight() -> None:
    source = format_physical_page_markdown(
        [
            (1, "08:00 UK Time\n\n## 1\n\nFind $x$. [1 mark]"),
            (16, "## 8\n\nFind $y$. [2 marks]\n\nEND OF QUESTIONS"),
        ]
    )

    structures = question_source_structures(source)

    assert [structure.number for structure in structures] == ["1", "8"]


def test_source_structure_ignores_equation_coefficient_before_question_ten() -> None:
    source = format_physical_page_markdown(
        [
            (3, "## 2\n\nThe point $A$ has given coordinates. [2 marks]"),
            (
                17,
                "## 9\n\nIt is given that\n\n"
                "2ax^2 + 7bx + 4c = 0\n\n"
                "Find the possible values. [5 marks]",
            ),
            (18, "## 10\n\nThe function $f$ is defined by $f(x)=x^2$. [3 marks]"),
        ]
    )

    structures = question_source_structures(source)

    assert [structure.number for structure in structures] == ["2", "9", "10"]


def test_source_structure_accepts_spaced_ocr_numbers_and_adjacent_bold_title() -> None:
    source = format_physical_page_markdown(
        [
            (
                3,
                "0 2 Shortages of grain have increased its price. [1 mark]\n\n"
                "0 3 Which statement describes the rationing function? [1 mark]",
            ),
            (
                10,
                "**14** In the short run, average fixed costs decrease. [1 mark]\n\n"
                "**15** **Figure 2** shows demand and supply. [1 mark]",
            ),
        ]
    )

    structures = question_source_structures(source)

    assert [structure.number for structure in structures] == ["2", "3", "14", "15"]
    assert [structure.marks for structure in structures] == [(1,), (1,), (1,), (1,)]


def test_source_structure_reads_decimal_subparts() -> None:
    source = format_physical_page_markdown(
        [
            (
                11,
                "**16.1** Define free market economy. **[3 marks]**\n\n"
                "**16.2** Define imperfect information. **[3 marks]**",
            )
        ]
    )

    [structure] = question_source_structures(source)

    assert structure.number == "16"
    assert structure.subpart_labels == (".1", ".2")
    assert structure.marks == (3, 3)
    assert "**16.1**" in structure.question_markdown
    assert "**16.2**" in structure.question_markdown


def test_source_structure_reads_spaced_ocr_decimal_subparts() -> None:
    source = format_physical_page_markdown(
        [
            (
                10,
                "**1 1** A commodity-price scenario.\n\n"
                "**1 1 . 1** State two uses of a buffer stock. **[2 marks]**\n\n"
                "**1 1 . 2** Calculate the percentage change. **[2 marks]**",
            ),
            (11, "**11.3** Explain the effect using a diagram. **[6 marks]**"),
        ]
    )

    [structure] = question_source_structures(source)

    assert structure.number == "11"
    assert structure.subpart_labels == (".1", ".2", ".3")
    assert structure.marks == (2, 2, 6)
    assert "**11.1**" in structure.question_markdown
    assert "**11.2**" in structure.question_markdown
    assert "**11.3**" in structure.question_markdown


def test_source_structure_keeps_explicit_heading_before_marked_decimal_subpart() -> None:
    source = format_physical_page_markdown(
        [
            (
                12,
                "**12** Extract A shows labour-force growth.\n\n"
                "**12.1** Explain why labour-force growth affects real GDP. "
                "**[4 marks]**",
            ),
            (
                13,
                "### 12.2\n\nUse Extract A to assess the effect. **[4 marks]**",
            ),
        ]
    )

    [structure] = question_source_structures(source)

    assert structure.number == "12"
    assert structure.subpart_labels == (".1", ".2")
    assert structure.marks == (4, 4)
    assert structure.question_markdown.startswith(
        "Extract A shows labour-force growth.\n\n**12.1**"
    )
    assert "### 12.2" in structure.question_markdown


def test_source_structure_accepts_question_prefixed_decimal_labels_in_parentheses() -> None:
    source = format_physical_page_markdown(
        [
            (
                10,
                "## 11\n\n11.1 State one reason. [2 marks]\n\n"
                "11.2 Calculate the value. [2 marks]\n\n"
                "11.3 Explain the effect. [6 marks]\n\nEND OF QUESTIONS",
            )
        ]
    )
    questions = [
        {
            "number": "11",
            "question_markdown": "Complete question 11.",
            "answer_requirements": [
                {"label": "(11.1)", "marks": 2, "answer_kind": "text"},
                {"label": "(11.2)", "marks": 2, "answer_kind": "numeric"},
                {"label": "(11.3)", "marks": 6, "answer_kind": "text"},
            ],
            "total_marks": 10,
        }
    ]

    [validated] = validate_question_source_structure(source, questions)

    assert [part["label"] for part in validated["answer_requirements"]] == [
        ".1",
        ".2",
        ".3",
    ]
    assert validated["total_marks"] == 10


def test_source_structure_accepts_equivalent_letter_aliases_for_decimal_subparts() -> None:
    source = format_physical_page_markdown(
        [
            (
                12,
                "17.1 Calculate the percentage. [2 marks]\n\n"
                "17.2 Calculate the elasticity. [4 marks]",
            )
        ]
    )
    questions = [
        {
            "number": "17",
            "question_markdown": "Model split output.",
            "answer_requirements": [
                {"label": "(a)", "marks": 2},
                {"label": "(b)", "marks": 4},
            ],
            "total_marks": 6,
        }
    ]

    [validated] = validate_question_source_structure(source, questions)

    assert [part["label"] for part in validated["answer_requirements"]] == [".1", ".2"]


def test_source_structure_normalizes_question_number_prefixed_model_labels() -> None:
    source = format_physical_page_markdown(
        [
            (
                7,
                "## 4\n\n4 (a) Find one value. [2 marks]\n\n4 (b) Find another value. [5 marks]",
            )
        ]
    )
    questions = [
        {
            "number": "4",
            "question_markdown": "Model split output.",
            "answer_requirements": [
                {"label": "4(a)", "marks": 2},
                {"label": "4(b)", "marks": 5},
            ],
            "total_marks": 7,
        }
    ]

    [validated] = validate_question_source_structure(source, questions)

    assert [part["label"] for part in validated["answer_requirements"]] == ["(a)", "(b)"]


def test_split_merge_prefers_structural_superset_across_primary_batch_overlap() -> None:
    partial = {
        "number": "4",
        "question_markdown": (
            "A business makes smartphones.\n\n"
            "(a) Find the probability. [2 marks]\n\n"
            "(b)(i) State the approximation conditions. [2 marks]"
        ),
        "answer_requirements": [
            {"label": "(a)", "marks": 2, "answer_kind": "numeric"},
            {"label": "(b)(i)", "marks": 2, "answer_kind": "text"},
        ],
        "_split_source": "primary",
        "_split_source_digest": "trusted-source",
        "_split_batch_index": 0,
    }
    complete = {
        "number": "4",
        "question_markdown": (
            "A business makes smartphones.\n\n"
            "4 (a) Find the probability.\n\n"
            "4 (b) (i) State the approximation conditions.\n\n"
            "4 (b) (ii) Use the approximation. [3 marks]"
        ),
        "answer_requirements": [
            {"label": "(a)", "marks": 2, "answer_kind": "numeric"},
            {"label": "(b)(i)", "marks": 2, "answer_kind": "text"},
            {"label": "(b)(ii)", "marks": 3, "answer_kind": "numeric"},
        ],
        "_split_source": "primary",
        "_split_source_digest": "trusted-source",
        "_split_batch_index": 1,
    }

    [merged] = _merge_split_questions([partial, complete])

    assert "Use the approximation" in merged["question_markdown"]
    assert [part["label"] for part in merged["answer_requirements"]] == [
        "(a)",
        "(b)(i)",
        "(b)(ii)",
    ]
    assert merged["total_marks"] == 7


def test_split_merge_resolves_explicit_proof_kind_across_overlapping_batches() -> None:
    stem = "A non-uniform rod is held in equilibrium."
    proof_part = (
        "(a)(i) By taking moments about A show that d is 1.622 "
        "correct to four significant figures. [3 marks]"
    )
    partial = {
        "number": "4",
        "question_markdown": f"{stem}\n\n{proof_part}",
        "answer_requirements": [
            {
                "label": "(a)(i)",
                "marks": 3,
                "answer_kind": "proof",
                "accuracy": "four significant figures",
                "units": ["m"],
            }
        ],
        "_split_source": "primary",
        "_split_source_digest": "trusted-source",
        "_split_batch_index": 1,
    }
    complete = {
        "number": "4",
        "question_markdown": (
            f"{stem}\n\n{proof_part}\n\n(a)(ii) Find the tension in the string. [2 marks]"
        ),
        "answer_requirements": [
            {
                "label": "(a)(i)",
                "marks": 3,
                "answer_kind": "numeric",
                "accuracy": "four significant figures",
            },
            {"label": "(a)(ii)", "marks": 2, "answer_kind": "numeric"},
        ],
        "_split_source": "primary",
        "_split_source_digest": "trusted-source",
        "_split_batch_index": 2,
    }

    [merged] = _merge_split_questions([partial, complete])

    assert merged["answer_requirements"] == [
        {
            "label": "(a)(i)",
            "marks": 3,
            "answer_kind": "proof",
            "accuracy": "four significant figures",
            "units": ["m"],
        },
        {"label": "(a)(ii)", "marks": 2, "answer_kind": "numeric"},
    ]
    assert merged["total_marks"] == 5


def test_split_merge_rejects_answer_kind_conflict_without_source_proof_directive() -> None:
    candidates = [
        {
            "number": "4",
            "question_markdown": "(a) Find the exact value of x. [2 marks]",
            "answer_requirements": [{"label": "(a)", "marks": 2, "answer_kind": "numeric"}],
            "_split_source": "primary",
            "_split_source_digest": "trusted-source",
            "_split_batch_index": 0,
        },
        {
            "number": "4",
            "question_markdown": "(a) Find the exact value of x. [2 marks]",
            "answer_requirements": [{"label": "(a)", "marks": 2, "answer_kind": "expression"}],
            "_split_source": "primary",
            "_split_source_digest": "trusted-source",
            "_split_batch_index": 1,
        },
    ]

    with pytest.raises(ValueError, match="answer_kind 冲突"):
        _merge_split_questions(candidates)


def test_split_merge_preserves_parent_context_for_nested_batch_continuation() -> None:
    opening = {
        "number": "5",
        "question_markdown": (
            "A particle is projected with speed u from a point O at height h.\n\n"
            "5 (a) Show that y is a quadratic function of x. [6 marks]"
        ),
        "answer_requirements": [{"label": "(a)", "marks": 6, "answer_kind": "proof"}],
        "_split_source": "primary",
        "_split_source_digest": "trusted-source",
        "_split_batch_index": 2,
    }
    continuation = {
        "number": "5",
        "question_markdown": (
            "5 (b) A particle is projected with speed 20 m/s at 25 degrees "
            "from a point O at height 4 m.\n\n"
            "5 (b) (i) Use part (a) to find its horizontal displacement. [3 marks]\n\n"
            "5 (b) (ii) Find the flight time T. [2 marks]"
        ),
        "answer_requirements": [
            {"label": "(b)(i)", "marks": 3, "answer_kind": "numeric"},
            {"label": "(b)(ii)", "marks": 2, "answer_kind": "numeric"},
        ],
        "_split_source": "primary",
        "_split_source_digest": "trusted-source",
        "_split_batch_index": 3,
    }

    [merged] = _merge_split_questions([opening, continuation])

    assert "(b) A particle is projected with speed 20 m/s" in merged["question_markdown"]
    assert [part["label"] for part in merged["answer_requirements"]] == [
        "(a)",
        "(b)(i)",
        "(b)(ii)",
    ]
    assert merged["total_marks"] == 11


def test_split_merge_rejects_conflicting_primary_stems() -> None:
    candidates = [
        {
            "number": "8",
            "question_markdown": (
                "Correct printed definition $F(x)=x^2$.\n\n(a) Find $h$. [2 marks]"
            ),
            "answer_requirements": [{"label": "(a)", "marks": 2}],
            "_split_source": "primary",
            "_split_source_digest": "trusted-source",
            "_split_batch_index": 0,
        },
        {
            "number": "8",
            "question_markdown": (
                "Longer transcription that silently omits the printed definition.\n\n"
                "(b) Find $g$. [2 marks]"
            ),
            "answer_requirements": [{"label": "(b)", "marks": 2}],
            "_split_source": "primary",
            "_split_source_digest": "trusted-source",
            "_split_batch_index": 1,
        },
    ]

    with pytest.raises(ValueError, match="主源题干冲突"):
        _merge_split_questions(candidates)


def test_split_merge_normalizes_question_number_prefixed_subpart_labels() -> None:
    candidates = [
        {
            "number": "4",
            "question_markdown": "4 (a) Find p. [5 marks]\n\n4 (b) Find q. [3 marks]",
            "answer_requirements": [
                {"label": "4 (a)", "marks": 5, "answer_kind": "numeric"},
                {"label": "4 (b)", "marks": 3, "answer_kind": "numeric"},
            ],
            "_split_source": "primary",
            "_split_source_digest": "trusted-source",
            "_split_batch_index": 0,
        },
        {
            "number": "4",
            "question_markdown": "4 (b) Find q. [3 marks]",
            "answer_requirements": [{"label": "(b)", "marks": 3, "answer_kind": "numeric"}],
            "_split_source": "primary",
            "_split_source_digest": "trusted-source",
            "_split_batch_index": 1,
        },
    ]

    [merged] = _merge_split_questions(candidates)

    assert [item["label"] for item in merged["answer_requirements"]] == ["(a)", "(b)"]
    assert merged["total_marks"] == 8


def test_split_merge_drops_whole_labeled_fragment_contained_in_complete_question() -> None:
    complete = {
        "number": "11",
        "question_markdown": (
            "According to the Prebisch-Singer hypothesis, primary commodity prices vary.\n\n"
            "(a) State the two ways in which a buffer stock is used to stabilise the price "
            "of a primary commodity.\n\n"
            "(b) Calculate the difference between the percentage changes."
        ),
        "source_pages": [10],
        "total_marks": 4,
        "answer_requirements": [
            {"label": "(a)", "marks": 2, "answer_kind": "text"},
            {"label": "(b)", "marks": 2, "answer_kind": "numeric"},
        ],
        "_split_source": "primary",
        "_split_source_digest": "trusted-source",
        "_split_batch_index": 8,
    }
    overlap_fragment = {
        "number": "11",
        "question_markdown": (
            "State the two ways in which a buffer stock is used to stabilise the price "
            "of a primary commodity. [2 marks]"
        ),
        "source_pages": [10],
        "total_marks": 2,
        "answer_requirements": [{"label": "whole", "marks": 2, "answer_kind": "text"}],
        "_split_source": "primary",
        "_split_source_digest": "trusted-source",
        "_split_batch_index": 9,
    }

    [merged] = _merge_split_questions([complete, overlap_fragment])

    assert merged["question_markdown"] == complete["question_markdown"]
    assert [part["label"] for part in merged["answer_requirements"]] == ["(a)", "(b)"]
    assert merged["total_marks"] == 4


def test_split_merge_accepts_duplicate_stems_that_only_differ_by_mark_annotation() -> None:
    base = {
        "number": "02",
        "source_pages": [3],
        "total_marks": 1,
        "answer_requirements": [{"label": "whole", "marks": 1, "answer_kind": "text"}],
        "_split_source": "primary",
        "_split_source_digest": "trusted-source",
    }
    without_annotation = {
        **base,
        "question_markdown": (
            "Which statement about the terms of trade is correct?\n\n"
            "A Exports rose.\n\nB Imports fell."
        ),
        "_split_batch_index": 0,
    }
    with_annotation = {
        **base,
        "question_markdown": (
            "Which statement about the terms of trade is correct?\n\n"
            "**[1 mark]**\n\nA Exports rose.\n\nB Imports fell."
        ),
        "_split_batch_index": 1,
    }

    [merged] = _merge_split_questions([without_annotation, with_annotation])

    assert "**[1 mark]**" in merged["question_markdown"]
    assert merged["total_marks"] == 1


def test_split_contract_rejects_silent_subpart_omission() -> None:
    source = format_physical_page_markdown(
        [
            (
                16,
                "8 The continuous random variable $X$ has distribution $F$.\n\n"
                "(a) Find $h$. [2 marks]\n\n"
                "(b) Find $g$. [3 marks]\n\nEND OF QUESTIONS",
            )
        ]
    )
    settings = Settings()
    service = PaperAnswerService(
        settings,
        subject_context(settings),
        splitter=lambda _markdown, _catalog: [
            {
                "number": "8",
                "question_markdown": (
                    "The continuous random variable $X$ has distribution $F$.\n\n"
                    "(a) Find $h$. [2 marks]"
                ),
                "requires_visual_context": False,
                "answer_requirements": [{"label": "(a)", "marks": 2, "answer_kind": "numeric"}],
            }
        ],
        catalog_loader=fake_catalog,
        rag=object(),
    )

    with pytest.raises(ValueError, match="子问结构与主源不一致"):
        service.split_questions_checkpointed(
            source,
            source_markdown=source,
            unit_code="P2",
            load_checkpoint=lambda _index, _digest: None,
            save_checkpoint=lambda _index, _count, _digest, _items, _duration: None,
        )


def test_split_contract_derives_visual_context_once_from_trusted_source() -> None:
    source = format_physical_page_markdown(
        [(5, "1 Figure 1 shows a shaded region. Find its area. [4 marks]\nEND OF QUESTIONS")]
    )
    settings = Settings()
    service = PaperAnswerService(
        settings,
        subject_context(settings),
        splitter=lambda _markdown, _catalog: [
            {
                "number": "1",
                "question_markdown": "Find its area. [4 marks]",
                "requires_visual_context": False,
                "answer_requirements": [{"label": "whole", "marks": 4, "answer_kind": "numeric"}],
            }
        ],
        catalog_loader=fake_catalog,
        rag=object(),
    )

    [question] = service.split_questions_checkpointed(
        source,
        source_markdown=source,
        unit_code="P2",
        load_checkpoint=lambda _index, _digest: None,
        save_checkpoint=lambda _index, _count, _digest, _items, _duration: None,
    )

    assert question["requires_visual_context"] is True
    assert question["question_markdown"].startswith("Figure 1")
    assert question["source_pages"] == [5]


def test_checkpointed_split_keeps_recovery_from_overwriting_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = format_physical_page_markdown(
        [
            (
                16,
                "8 The continuous random variable $X$ has cumulative distribution function "
                "$F(x)=x^2$ for $0\\le x\\le1$.\n\n(a) Find $F(1)$. [2 marks]",
            )
        ]
    )
    recovery = "## PDF text-layer recovery appendix\n" + format_physical_page_markdown(
        [
            (
                16,
                "8 The continuous random variable X has a cumulative distribution "
                "function with [piecewise definition as printed]. "
                "(a) Find F(1). [2 marks]",
            )
        ]
    )
    source_roles: list[str] = []

    class FakeLLM:
        def complete(self, prompt: str) -> SimpleNamespace:
            recovery_batch = "RECOVERY text-layer appendix" in prompt
            source_roles.append("recovery" if recovery_batch else "primary")
            question_markdown = (
                "The continuous random variable $X$ has cumulative distribution function "
                "with [piecewise definition as printed].\n\n(a) Find $F(1)$. [2 marks]"
                if recovery_batch
                else "The continuous random variable $X$ has cumulative distribution "
                "function $F(x)=x^2$ for $0\\le x\\le1$.\n\n"
                "(a) Find $F(1)$. [2 marks]"
            )
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "questions": [
                            {
                                "number": "8",
                                "question_markdown": question_markdown,
                                "source_pages": [16],
                                "requires_visual_context": False,
                                "total_marks": 2,
                                "answer_requirements": [
                                    {
                                        "label": "(a)",
                                        "marks": 2,
                                        "answer_kind": "numeric",
                                        "accuracy": None,
                                        "units": [],
                                        "required_tool": None,
                                    }
                                ],
                            }
                        ]
                    }
                )
            )

    monkeypatch.setattr(
        "examtwin.assessment.paper_answering.build_llm",
        lambda *_args, **_kwargs: FakeLLM(),
    )
    settings = Settings(paper_split_max_chars=20_000)
    service = PaperAnswerService(
        settings,
        subject_context(settings),
        catalog_loader=fake_catalog,
        rag=object(),
    )

    [question] = service.split_questions_checkpointed(
        f"{primary}\n\n{recovery}",
        source_markdown=primary,
        unit_code="P2",
        load_checkpoint=lambda _index, _digest: None,
        save_checkpoint=lambda _index, _count, _digest, _items, _duration: None,
    )

    assert sorted(source_roles) == ["primary", "recovery"]
    assert "$F(x)=x^2$" in question["question_markdown"]
    assert "piecewise definition as printed" not in question["question_markdown"]
    assert question["source_pages"] == [16]


class FakeQuestionRepairModel:
    model_name = "question-repair-test"

    def __init__(self, groups: list[dict[str, Any]]) -> None:
        self.groups = groups
        self.calls = 0

    def complete(
        self,
        _messages: Any,
        response_model: Any,
        *,
        timeout: float,
    ) -> Any:
        assert timeout > 0
        self.calls += 1
        return response_model.model_validate({"groups": self.groups})


class SequencedQuestionRepairModel:
    model_name = "question-repair-test"

    def __init__(self, plans: list[list[dict[str, Any]]]) -> None:
        self.plans = plans
        self.calls = 0
        self.messages: list[Any] = []

    def complete(
        self,
        messages: Any,
        response_model: Any,
        *,
        timeout: float,
    ) -> Any:
        assert timeout > 0
        self.messages.append(messages)
        plan = self.plans[min(self.calls, len(self.plans) - 1)]
        self.calls += 1
        return response_model.model_validate({"groups": plan})


def test_split_uses_structured_repair_only_after_source_reconciliation_fails() -> None:
    source_markdown = format_physical_page_markdown(
        [
            (1, "1 Evaluate the alpha integral. [1 mark]"),
            (2, "2 Calculate the Latvian median flood payment. [1 mark]"),
            (3, "3 Draw an equilibrium supply diagram. [1 mark]\nEND OF QUESTIONS"),
        ]
    )
    candidates = [
        {"number": "1", "question_markdown": "Evaluate the alpha integral. [1 mark]"},
        {"number": "3", "question_markdown": "Draw an equilibrium supply diagram. [1 mark]"},
        {
            "number": "2",
            "question_markdown": "Calculate the Latvian median flood payment. [1 mark]",
        },
    ]
    model = FakeQuestionRepairModel(
        [
            {"number": "1", "candidate_indexes": [0]},
            {"number": "2", "candidate_indexes": [2]},
            {"number": "3", "candidate_indexes": [1]},
        ]
    )
    service = PaperAnswerService(
        Settings(),
        subject_context(Settings()),
        splitter=lambda _markdown, _catalog: candidates,
        catalog_loader=fake_catalog,
        rag=object(),
        structured_model=model,
    )

    result = service.split_questions(source_markdown, unit_code="P2")

    assert model.calls == 1
    assert [item["number"] for item in result] == ["1", "2", "3"]
    assert [item["source_pages"] for item in result] == [[1], [2], [3]]


def test_split_does_not_call_structured_repair_for_valid_source_order() -> None:
    source_markdown = format_physical_page_markdown(
        [(1, "1 First question text."), (2, "2 Second question text.")]
    )
    candidates = [
        {"number": "1", "question_markdown": "First question text."},
        {"number": "2", "question_markdown": "Second question text."},
    ]
    model = FakeQuestionRepairModel([])
    service = PaperAnswerService(
        Settings(),
        subject_context(Settings()),
        splitter=lambda _markdown, _catalog: candidates,
        catalog_loader=fake_catalog,
        rag=object(),
        structured_model=model,
    )

    result = service.split_questions(source_markdown, unit_code="P2")

    assert model.calls == 0
    assert [item["source_pages"] for item in result] == [[1], [2]]


def test_split_rejects_structured_repair_that_drops_a_candidate() -> None:
    source_markdown = format_physical_page_markdown(
        [
            (1, "1 Evaluate the alpha integral."),
            (2, "2 Calculate the Latvian median flood payment."),
            (3, "3 Draw an equilibrium supply diagram."),
        ]
    )
    candidates = [
        {"number": "1", "question_markdown": "Evaluate the alpha integral."},
        {"number": "3", "question_markdown": "Draw an equilibrium supply diagram."},
        {
            "number": "2",
            "question_markdown": "Calculate the Latvian median flood payment.",
        },
    ]
    model = FakeQuestionRepairModel(
        [
            {"number": "1", "candidate_indexes": [0]},
            {"number": "3", "candidate_indexes": [1]},
        ]
    )
    service = PaperAnswerService(
        Settings(),
        subject_context(Settings()),
        splitter=lambda _markdown, _catalog: candidates,
        catalog_loader=fake_catalog,
        rag=object(),
        structured_model=model,
    )

    with pytest.raises(ValueError, match="恰好使用一次"):
        service.split_questions(source_markdown, unit_code="P2")

    assert model.calls == 2


def test_split_retries_once_with_deterministic_candidate_feedback() -> None:
    source_markdown = format_physical_page_markdown(
        [
            (1, "1 Evaluate the alpha integral."),
            (2, "2 Calculate the Latvian median flood payment."),
            (3, "3 Draw an equilibrium supply diagram."),
        ]
    )
    candidates = [
        {"number": "1", "question_markdown": "Evaluate the alpha integral."},
        {"number": "3", "question_markdown": "Draw an equilibrium supply diagram."},
        {
            "number": "2",
            "question_markdown": "Calculate the Latvian median flood payment.",
        },
    ]
    model = SequencedQuestionRepairModel(
        [
            [
                {"number": "1", "candidate_indexes": [0]},
                {"number": "3", "candidate_indexes": [1]},
            ],
            [
                {"number": "1", "candidate_indexes": [0]},
                {"number": "2", "candidate_indexes": [2]},
                {"number": "3", "candidate_indexes": [1]},
            ],
        ]
    )
    service = PaperAnswerService(
        Settings(),
        subject_context(Settings()),
        splitter=lambda _markdown, _catalog: candidates,
        catalog_loader=fake_catalog,
        rag=object(),
        structured_model=model,
    )

    result = service.split_questions(source_markdown, unit_code="P2")

    assert model.calls == 2
    assert [item["number"] for item in result] == ["1", "2", "3"]
    correction_payload = json.loads(model.messages[1][1].content)
    assert correction_payload["missing_candidate_indexes"] == [2]
    assert correction_payload["duplicate_candidate_indexes"] == []
    assert correction_payload["invalid_candidate_indexes"] == []
    assert correction_payload["deterministic_validation_error"] == (
        "结构修复模型必须将每个候选题恰好使用一次"
    )


def test_split_uses_model_selected_candidate_for_overlapping_primary_conflicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_markdown = format_physical_page_markdown(
        [
            (
                17,
                "9 The polynomial is $p(x)=x^3+5x^2-x-21$.\n\n"
                "(a) Show that $a=5$. [2 marks]\n\n"
                "(b) Factorise $p(x)$. [3 marks]",
            ),
            (
                19,
                "10 A geometric series has positive common ratio $r$.\n\n"
                "(a) Find the allowed values. [3 marks]\n\n"
                "(b) Find the sum. [4 marks]\n\nEND OF QUESTIONS",
            ),
        ]
    )
    candidates = [
        {
            "number": "9",
            "question_markdown": (
                "The polynomial is $p(x)=x^3+5x^2-x-2 1$.\n\n"
                "(a) Show that $a=5$. [2 marks]\n\n"
                "(b) Factorise $p(x)$. [3 marks]"
            ),
            "answer_requirements": [
                {"label": "(a)", "marks": 2, "answer_kind": "proof"},
                {"label": "(b)", "marks": 3, "answer_kind": "expression"},
            ],
            "_split_source": "primary",
            "_split_source_digest": "trusted-source",
            "_split_batch_index": 1,
        },
        {
            "number": "9",
            "question_markdown": (
                "The polynomial is $p(x)=x^3+5x^2-x-21$.\n\n"
                "(a) Show that $a=5$. [2 marks]\n\n"
                "(b) Factorise $p(x)$. [3 marks]"
            ),
            "answer_requirements": [
                {"label": "(a)", "marks": 2, "answer_kind": "proof"},
                {"label": "(b)", "marks": 3, "answer_kind": "expression"},
            ],
            "_split_source": "primary",
            "_split_source_digest": "trusted-source",
            "_split_batch_index": 2,
        },
        {
            "number": "10",
            "question_markdown": "A geometric series has ratio q. [3 marks]",
            "answer_requirements": [{"label": "whole", "marks": 3, "answer_kind": "numeric"}],
            "_split_source": "primary",
            "_split_source_digest": "trusted-source",
            "_split_batch_index": 2,
        },
        {
            "number": "10",
            "question_markdown": (
                "A geometric series has positive common ratio $r$.\n\n"
                "(a) Find the allowed values. [3 marks]\n\n"
                "(b) Find the sum. [4 marks]"
            ),
            "answer_requirements": [
                {"label": "(a)", "marks": 3, "answer_kind": "expression"},
                {"label": "(b)", "marks": 4, "answer_kind": "numeric"},
            ],
            "_split_source": "primary",
            "_split_source_digest": "trusted-source",
            "_split_batch_index": 3,
        },
    ]
    model = FakeQuestionRepairModel(
        [
            {
                "number": "9",
                "candidate_indexes": [0, 1],
                "preferred_candidate_index": 1,
            },
            {
                "number": "10",
                "candidate_indexes": [2, 3],
                "preferred_candidate_index": 3,
            },
        ]
    )
    settings = Settings()
    service = PaperAnswerService(
        settings,
        subject_context(settings),
        catalog_loader=fake_catalog,
        rag=object(),
        structured_model=model,
    )
    monkeypatch.setattr(service, "_split_with_llm", lambda *_args, **_kwargs: candidates)

    result = service.split_questions(source_markdown, unit_code="P2")

    assert model.calls == 1
    assert [item["number"] for item in result] == ["9", "10"]
    assert "$p(x)=x^3+5x^2-x-21$" in result[0]["question_markdown"]
    assert [part["label"] for part in result[1]["answer_requirements"]] == ["(a)", "(b)"]
    assert result[1]["total_marks"] == 7
    assert not any(key.startswith("_split_") for item in result for key in item)


def test_split_uses_model_selected_candidate_after_final_source_structure_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_markdown = format_physical_page_markdown(
        [
            (
                11,
                "**16.1** Define free market economy. **[3 marks]**\n\n"
                "**16.2** Define imperfect information. **[3 marks]**",
            )
        ]
    )
    candidates = [
        {
            "number": "16",
            "question_markdown": (
                "16.1 Define free market economy. [3 marks]\n\n"
                "16.2 Define imperfect information. [3 marks]"
            ),
            "answer_requirements": [
                {"label": "16.1", "marks": 3, "answer_kind": "text"},
                {"label": "16.2", "marks": 3, "answer_kind": "text"},
            ],
            "_split_source": "primary",
            "_split_source_digest": "trusted-source",
            "_split_batch_index": 4,
        },
        {
            "number": "16",
            "question_markdown": (
                "(a) Define free market economy. [3 marks]\n\n"
                "(b) Define imperfect information. [3 marks]"
            ),
            "answer_requirements": [
                {"label": "(a)", "marks": 3, "answer_kind": "text"},
                {"label": "(b)", "marks": 3, "answer_kind": "text"},
            ],
            "_split_source": "primary",
            "_split_source_digest": "trusted-source",
            "_split_batch_index": 5,
        },
    ]
    model = FakeQuestionRepairModel(
        [
            {
                "number": "16",
                "candidate_indexes": [0, 1],
                "preferred_candidate_index": 1,
            }
        ]
    )
    settings = Settings()
    service = PaperAnswerService(
        settings,
        subject_context(settings),
        catalog_loader=fake_catalog,
        rag=object(),
        structured_model=model,
    )
    monkeypatch.setattr(service, "_split_with_llm", lambda *_args, **_kwargs: candidates)

    [result] = service.split_questions(source_markdown, unit_code="P2")

    assert model.calls == 1
    assert [part["label"] for part in result["answer_requirements"]] == [".1", ".2"]
    assert result["total_marks"] == 6


@pytest.mark.parametrize(
    ("preferred_candidate_index", "expected_error"),
    [(None, "必须为第 1 题选择权威候选"), (2, "组外候选")],
)
def test_split_rejects_invalid_model_candidate_selection(
    monkeypatch: pytest.MonkeyPatch,
    preferred_candidate_index: int | None,
    expected_error: str,
) -> None:
    source_markdown = format_physical_page_markdown(
        [(1, "1 Find $x$. [2 marks]\n\nEND OF QUESTIONS")]
    )
    candidates = [
        {
            "number": "1",
            "question_markdown": "Find $x$. [2 marks]",
            "answer_requirements": [{"label": "whole", "marks": 2, "answer_kind": "numeric"}],
            "_split_source": "primary",
            "_split_source_digest": "trusted-source",
            "_split_batch_index": 0,
        },
        {
            "number": "1",
            "question_markdown": "Find a different $x$. [2 marks]",
            "answer_requirements": [{"label": "whole", "marks": 2, "answer_kind": "numeric"}],
            "_split_source": "primary",
            "_split_source_digest": "trusted-source",
            "_split_batch_index": 1,
        },
    ]
    model = FakeQuestionRepairModel(
        [
            {
                "number": "1",
                "candidate_indexes": [0, 1],
                "preferred_candidate_index": preferred_candidate_index,
            }
        ]
    )
    settings = Settings()
    service = PaperAnswerService(
        settings,
        subject_context(settings),
        catalog_loader=fake_catalog,
        rag=object(),
        structured_model=model,
    )
    monkeypatch.setattr(service, "_split_with_llm", lambda *_args, **_kwargs: candidates)

    with pytest.raises(ValueError, match=expected_error):
        service.split_questions(source_markdown, unit_code="P2")


class FakeRag:
    def __init__(self) -> None:
        self.question_images: tuple[Any, ...] = ()
        self.visual_request_text: str | None = None
        self.question_number: str | None = None
        self.question_spec: Any | None = None

    def ask(
        self,
        request: Any,
        *,
        question_images: tuple[Any, ...] = (),
        question_number: str | None = None,
        question_spec: Any | None = None,
        visual_request_text: str | None = None,
        event_sink: Any | None = None,
    ) -> AskResponse:
        del event_sink
        self.question_images = question_images
        self.question_number = question_number
        self.question_spec = question_spec
        self.visual_request_text = visual_request_text
        if "broken" in request.question:
            raise RuntimeError("provider unavailable")
        return AskResponse(
            answer_markdown="Use integration by parts. [S1]",
            citations=[
                Citation(
                    source="spec.pdf",
                    page=22,
                    source_type="syllabus",
                    excerpt="Integration by parts.",
                    knowledge_code="P2.7.O03",
                )
            ],
            confidence=0.84,
            grounded=True,
        )


def test_uploaded_markdown_paper_is_answered_in_order_with_partial_failure() -> None:
    splitter = lambda _text, _catalog: [  # noqa: E731
        {
            "number": "1",
            "question_markdown": "Evaluate an integral using integration by parts.",
            "knowledge_codes": ["P2.7.O03"],
        },
        {
            "number": "2",
            "question_markdown": "broken provider question",
            "knowledge_codes": [],
        },
    ]
    service = PaperAnswerService(
        Settings(),
        subject_context(Settings()),
        rag=FakeRag(),
        splitter=splitter,
        parser=lambda _settings, _filename, body: body.decode(),
        catalog_loader=fake_catalog,
    )

    result = service.answer(
        "paper.md",
        b"# Paper\nEnough content for two questions.",
        unit_code="P2",
    )

    assert result.detected_questions == 2
    assert result.succeeded == 1
    assert result.failed == 1
    assert [item.number for item in result.questions] == ["1", "2"]
    assert result.questions[0].knowledge_points[0].code == "P2.7.O03"
    assert result.questions[0].citations[0].page == 22
    assert result.questions[1].error == "provider unavailable"


def test_empty_split_codes_are_mapped_from_cited_evidence_in_answer_order() -> None:
    catalog = [
        *fake_catalog(None),
        {
            "id": "9660:P2.7.O04",
            "code": "P2.7.O04",
            "title": "Definite integration.",
            "source_ref": "spec.pdf#page=23",
            "difficulty_score": 0.64,
            "difficulty_label": "medium",
            "difficulty_confidence": 0.3,
            "evidence_level": "D",
            "references": [],
            "features": {
                "node_type": "learning_objective",
                "description": "Evaluate a definite integral using its limits.",
            },
        },
    ]
    for objective_index in range(5, 8):
        code = f"P2.7.O{objective_index:02d}"
        catalog.append(
            {
                "id": f"9660:{code}",
                "code": code,
                "title": f"Integration objective {objective_index}.",
                "source_ref": f"spec.pdf#objective={objective_index}",
                "difficulty_score": 0.5,
                "difficulty_label": "medium",
                "difficulty_confidence": 0.3,
                "evidence_level": "D",
                "references": [],
                "features": {
                    "node_type": "learning_objective",
                    "description": f"Evidence-backed objective {objective_index}.",
                },
            }
        )

    class CitationMappedRag:
        request: Any | None = None

        def ask(self, request: Any, **_kwargs: Any) -> AskResponse:
            self.request = request
            return AskResponse(
                answer_markdown=(
                    "Apply the limits [S2], then integration by parts [S1]. Reuse [S2] and "
                    "check the remaining steps [S3] [S4] [S5] [S6]."
                ),
                citations=[
                    Citation(
                        source="integration-by-parts.pdf",
                        excerpt="Reverse the product rule.",
                        knowledge_code="P2.7.O03",
                    ),
                    Citation(
                        source="definite-integration.pdf",
                        excerpt="Apply the upper and lower limits.",
                        knowledge_code="P2.7.O04",
                    ),
                    Citation(
                        source="uncoded.pdf",
                        excerpt="Integration by parts.",
                    ),
                    Citation(
                        source="objective-5.pdf",
                        excerpt="Objective five.",
                        knowledge_code="P2.7.O05",
                    ),
                    Citation(
                        source="objective-6.pdf",
                        excerpt="Objective six.",
                        knowledge_code="P2.7.O06",
                    ),
                    Citation(
                        source="objective-7.pdf",
                        excerpt="Objective seven.",
                        knowledge_code="P2.7.O07",
                    ),
                ],
                confidence=0.9,
                grounded=True,
            )

    rag = CitationMappedRag()
    settings = Settings()
    service = PaperAnswerService(
        settings,
        subject_context(settings),
        rag=rag,
        catalog_loader=lambda _unit_code: catalog,
    )

    result = service.answer_question(
        {
            "number": "1",
            "question_markdown": "Evaluate this definite integral using integration by parts.",
            "knowledge_codes": [],
        },
        unit_code="P2",
    )

    assert rag.request is not None
    assert "Relevant knowledge:" not in rag.request.question
    assert [point.code for point in result.knowledge_points] == [
        "P2.7.O04",
        "P2.7.O03",
        "P2.7.O05",
        "P2.7.O06",
    ]
    assert [citation.source for citation in result.knowledge_points[0].references] == [
        "definite-integration.pdf"
    ]


def test_splitter_guessed_code_does_not_bias_answer_retrieval() -> None:
    catalog = [
        *fake_catalog(None),
        {
            "id": "9660:P2.7.O04",
            "code": "P2.7.O04",
            "title": "Definite integration.",
            "source_ref": "spec.pdf#page=23",
            "difficulty_score": 0.64,
            "difficulty_label": "medium",
            "difficulty_confidence": 0.3,
            "evidence_level": "D",
            "references": [],
            "features": {
                "node_type": "learning_objective",
                "description": "Evaluate a definite integral using its limits.",
            },
        },
    ]

    class CitationMappedRag:
        request: Any | None = None

        def ask(self, request: Any, **_kwargs: Any) -> AskResponse:
            self.request = request
            return AskResponse(
                answer_markdown="Apply the limits [S1].",
                citations=[
                    Citation(
                        source="definite-integration.pdf",
                        excerpt="Apply the upper and lower limits.",
                        knowledge_code="P2.7.O04",
                    )
                ],
                confidence=0.9,
                grounded=True,
            )

    rag = CitationMappedRag()
    settings = Settings()
    service = PaperAnswerService(
        settings,
        subject_context(settings),
        rag=rag,
        catalog_loader=lambda _unit_code: catalog,
    )

    result = service.answer_question(
        {
            "number": "1",
            "question_markdown": "Evaluate this definite integral.",
            "knowledge_codes": ["P2.7.O03"],
        },
        unit_code="P2",
    )

    assert rag.request is not None
    assert "Relevant knowledge:" not in rag.request.question
    assert [point.code for point in result.knowledge_points] == ["P2.7.O04"]


def test_catalog_keeps_subject_scope_for_synoptic_papers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def load_points(_repository: Any, **filters: Any) -> list[dict[str, Any]]:
        captured.update(filters)
        return fake_catalog(None)

    monkeypatch.setattr(
        "examtwin.assessment.paper_answering.list_knowledge_points",
        load_points,
    )
    settings = Settings()
    service = PaperAnswerService(
        settings,
        subject_context(settings),
        knowledge_repository=object(),  # type: ignore[arg-type]
        rag=object(),
    )

    service._load_catalog("P2")

    assert captured == {"subject_code": "9660", "unit_code": None}


def test_uncoded_citation_does_not_trigger_lexical_knowledge_fallback() -> None:
    class UncodedRag:
        def ask(self, _request: Any, **_kwargs: Any) -> AskResponse:
            return AskResponse(
                answer_markdown="Use integration by parts [S1].",
                citations=[
                    Citation(
                        source="uncoded.pdf",
                        excerpt="Integration by parts.",
                    )
                ],
                confidence=0.8,
                grounded=True,
            )

    settings = Settings()
    service = PaperAnswerService(
        settings,
        subject_context(settings),
        rag=UncodedRag(),
        catalog_loader=fake_catalog,
    )

    result = service.answer_question(
        {
            "number": "1",
            "question_markdown": "Evaluate an integral using integration by parts.",
            "knowledge_codes": [],
        },
        unit_code="P2",
    )

    assert result.knowledge_points == []


def test_markdown_upload_accepts_utf8_bom_and_rejects_unknown_type() -> None:
    settings = Settings()
    assert upload_to_markdown(settings, "paper.md", b"\xef\xbb\xbf# Question 1") == "# Question 1"

    try:
        upload_to_markdown(settings, "paper.docx", b"content")
    except ValueError as error:
        assert "Markdown" in str(error)
    else:
        raise AssertionError("unsupported upload should fail")


def test_paper_answer_service_forwards_trusted_question_images_to_rag() -> None:
    rag = FakeRag()
    service = PaperAnswerService(
        Settings(),
        subject_context(Settings()),
        rag=rag,
        catalog_loader=fake_catalog,
    )
    image = QuestionImage(page_number=2, content=b"\xff\xd8page-2")

    result = service.answer_question(
        {
            "number": "1",
            "question_markdown": "Use Figure 1 to find the value.",
            "knowledge_codes": ["P2.7.O03"],
            "question_images": (image,),
            "answer_requirements": [
                {
                    "label": "(a)",
                    "marks": 3,
                    "answer_kind": "numeric",
                    "accuracy": "three significant figures",
                }
            ],
        },
        unit_code="P2",
        pair_key="9660:2026:JUN:P2",
    )

    assert result.answer_markdown
    assert rag.question_images == (image,)
    assert rag.visual_request_text == "Use Figure 1 to find the value."
    assert rag.question_number == "1"
    assert rag.question_spec.subparts[0].accuracy == "three significant figures"


def test_visual_context_classification_skips_text_probability_but_keeps_graphs() -> None:
    assert (
        question_requires_visual_context(
            "Find the probability that exactly 2 of 20 smartphones are faulty."
        )
        is False
    )
    assert question_requires_visual_context(
        "Figure 5 shows two curves and a finite shaded region. Find its area."
    )
    assert (
        question_requires_visual_context(
            "Explain, using a demand and supply diagram, the effect on total revenue."
        )
        is False
    )


def test_unresolved_printed_source_placeholder_requires_repair() -> None:
    placeholder = (
        "$F(x)=\\begin{cases}"
        "\\text{[piecewise definition as printed]},&"
        "\\text{[ranges as printed]}"
        "\\end{cases}$"
    )

    assert question_has_unresolved_source_placeholder(placeholder)
    assert question_requires_visual_context(placeholder)
    assert not question_has_unresolved_source_placeholder(
        "$F(x)=\\begin{cases}0,&x<1\\\\x^2,&1\\le x<2\\end{cases}$"
    )


def test_split_rejects_unresolved_source_placeholder_before_persistence() -> None:
    settings = Settings()
    service = PaperAnswerService(
        settings,
        subject_context(settings),
        splitter=lambda _markdown, _catalog: [
            {
                "number": "8",
                "question_markdown": (
                    "$F(x)=\\text{[piecewise definition as printed]}$. "
                    "Find the value of $h$. [2 marks]"
                ),
                "answer_requirements": [{"label": "whole", "marks": 2, "answer_kind": "numeric"}],
            }
        ],
        catalog_loader=fake_catalog,
        rag=object(),
    )

    with pytest.raises(ValueError, match="未修复的原卷占位符"):
        service.split_questions("8 " + ("source " * 10), unit_code="P2")


def test_source_pages_match_markdown_heading_number_on_own_line() -> None:
    markdown = format_physical_page_markdown(
        [
            (
                5,
                "Context material before the questions.\n\n"
                "### 06\n\nExplain why routine work is at risk.\n\n"
                "### 07\n\n**Extract E** says technology affects wages.\n\n"
                "### 08\n\n**Extract F** asks whether governments should intervene.",
            ),
        ]
    )
    questions = [
        {
            "number": "06",
            "question_markdown": "Explain why routine work is at risk.",
            "source_pages": [99],
        },
        {
            "number": "07",
            "question_markdown": "Explain how technology affects wages.",
            "source_pages": [99],
        },
        {
            "number": "08",
            "question_markdown": "Evaluate whether governments should intervene.",
            "source_pages": [99],
        },
    ]

    reconciled = reconcile_question_source_pages(markdown, questions)

    assert [item["source_pages"] for item in reconciled] == [[5], [5], [5]]


def test_source_pages_include_referenced_extract_before_question_page() -> None:
    markdown = format_physical_page_markdown(
        [
            (2, "## Extract A: Customer switching data\n\nNationwide: gains 150, losses 40."),
            (
                3,
                "### 01\n\nUsing **Extract A**, calculate the ratio.\n\nEND OF QUESTIONS",
            ),
        ]
    )
    questions = [
        {
            "number": "01",
            "question_markdown": "Using Extract A, calculate the ratio.",
            "source_pages": [99],
        }
    ]

    reconciled = reconcile_question_source_pages(markdown, questions)

    assert reconciled[0]["source_pages"] == [2, 3]


def test_source_pages_are_derived_from_physical_order_across_chunks() -> None:
    markdown = (
        "<!-- pages 1-5 -->\n"
        + format_physical_page_markdown(
            [
                (1, ""),
                (2, "1 (a) Find x. [2 marks]"),
                (
                    3,
                    "1 (b) Hence find y. [3 marks]\n2 (a) State the distribution. [1 mark]",
                ),
                (4, ""),
                (5, "2 (b) Calculate the probability. [4 marks]"),
            ]
        )
        + "\n\n<!-- pages 6-7 -->\n"
        + format_physical_page_markdown(
            [
                (
                    6,
                    "Continue question 2: give the final value. [1 mark]\n"
                    "3 Show that the estimator is unbiased. [4 marks]\n"
                    "4 (a) Write down the hypotheses. [2 marks]",
                ),
                (7, "4 (b) Carry out the test. [5 marks]"),
            ]
        )
    )
    questions = [
        {
            "number": "1",
            "question_markdown": "Find x and hence find y.",
            "source_pages": [99],
        },
        {
            "number": "2",
            "question_markdown": "State the distribution and calculate the probability.",
            "source_pages": [1],
        },
        {
            "number": "3",
            "question_markdown": "Show that the estimator is unbiased.",
            "source_pages": [],
        },
        {
            "number": "4",
            "question_markdown": "Write down the hypotheses and carry out the test.",
            "source_pages": [7],
        },
    ]

    reconciled = reconcile_question_source_pages(markdown, questions)

    assert [item["source_pages"] for item in reconciled] == [
        [2, 3],
        [3, 5, 6],
        [6],
        [6, 7],
    ]


def test_source_pages_exclude_real_9660_tail_administration() -> None:
    markdown = format_physical_page_markdown(
        [
            (
                16,
                "8 The continuous random variable X has a cumulative distribution "
                "function F(x).\n8 (a) Find h.\n8 (b) Find g.",
            ),
            (
                17,
                "8 (c) Find the probability density function f(x) of X.\n"
                "Question 8 continues on the next page.\nTurn over.",
            ),
            (
                18,
                "8 (d) Find the exact value of E(1/X). Give your answer in the "
                "form p ln 3 + q ln 4 - 13/45.",
            ),
            (
                19,
                "Turn over for the next question\n\n"
                "DO NOT WRITE ON THIS PAGE\n"
                "ANSWER IN THE SPACES PROVIDED",
            ),
            (
                20,
                "9 The discrete random variables X and Y follow independent Poisson "
                "distributions.\n9 (a) Find the mean of T.\n"
                "9 (b) Find P(Y >= 10).",
            ),
            (
                21,
                "9 (c) Find P(T < 8 | Y = 5).\n\nEND OF QUESTIONS",
            ),
            (
                22,
                "There are no questions printed on this page.\nDO NOT WRITE ON THIS PAGE",
            ),
            (
                23,
                "Question number\nAdditional page, if required.\n"
                "Write the question numbers in the left-hand margin.",
            ),
            (
                24,
                "Question number\nAdditional page, if required.\nCopyright information",
            ),
        ]
    )
    questions = [
        {
            "number": "8",
            "question_markdown": (
                "Find h and g, find the probability density function f(x), "
                "and find the exact value of E(1/X)."
            ),
            "source_pages": [16, 19],
        },
        {
            "number": "9",
            "question_markdown": (
                "For independent Poisson variables, find the mean of T, "
                "P(Y >= 10), and P(T < 8 | Y = 5)."
            ),
            "source_pages": [20, 24],
        },
    ]

    reconciled = reconcile_question_source_pages(markdown, questions)

    assert [item["source_pages"] for item in reconciled] == [
        [16, 17, 18],
        [20, 21],
    ]


def test_source_pages_keep_diagram_only_continuation_page() -> None:
    markdown = format_physical_page_markdown(
        [
            (1, "1 Sketch the transformation shown in Figure 1."),
            (2, "[visual content only]"),
            (3, "2 Find the value of x."),
        ]
    )
    questions = [
        {
            "number": "1",
            "question_markdown": "Sketch the transformation shown in Figure 1.",
        },
        {
            "number": "2",
            "question_markdown": "Find the value of x.",
        },
    ]

    reconciled = reconcile_question_source_pages(markdown, questions)

    assert [item["source_pages"] for item in reconciled] == [[1, 2], [3]]


def test_split_questions_rejects_unverifiable_model_page_guess() -> None:
    markdown = format_physical_page_markdown(
        [(1, "This page contains instructions but no examination question.")]
    )
    questions = [
        {
            "number": "9",
            "question_markdown": "Evaluate a trigonometric integral.",
            "source_pages": [1],
            "knowledge_codes": [],
        }
    ]

    try:
        reconcile_question_source_pages(markdown, questions)
    except ValueError as error:
        assert "无法从物理页标记" in str(error)
    else:
        raise AssertionError("unverifiable model page guess should be rejected")
