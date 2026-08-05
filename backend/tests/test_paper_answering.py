from __future__ import annotations

import json
import re
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest
from examtwin.answering_agent.contracts import QuestionImage
from examtwin.config import Settings
from examtwin.schemas import AskResponse, Citation
from examtwin.services.paper_answering import PaperAnswerService, _split_markdown_batches
from examtwin.services.paper_parsing import (
    question_requires_visual_context,
    reconcile_question_source_pages,
    upload_to_markdown,
)
from examtwin.services.paper_vision import format_physical_page_markdown
from examtwin.services.subject_context import subject_context


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
        "examtwin.services.paper_answering.build_llm",
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
