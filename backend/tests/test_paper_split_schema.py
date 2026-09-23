from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import httpx
import pytest
from examtwin.assessment.paper_answering import PaperAnswerService, _QuestionSplitPayload
from examtwin.assessment.paper_parsing import question_spec_from_item
from examtwin.assessment.paper_vision import format_physical_page_markdown
from examtwin.platform.config import Settings
from examtwin.subjects.public import subject_context
from jsonschema import Draft202012Validator
from openai import OpenAI
from pydantic import ValidationError


def _assert_closed_objects(node: Any) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False
            assert node.get("properties")  # Not an empty object used to hide the bug.
            assert set(node["required"]) == set(node["properties"])
        for value in node.values():
            _assert_closed_objects(value)
    elif isinstance(node, list):
        for value in node:
            _assert_closed_objects(value)


def test_split_emits_strict_provider_schema_and_preserves_source_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exercise the real adapter, LiteLLM schema conversion and SDK serialization;
    # only the HTTP transport is replaced. No credentials or live model are used.
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    from litellm.llms.openai.openai import OpenAIChatCompletion

    question_text = (
        "1 A particle moves along a straight line.\n"
        "(a) Find its speed in m/s to three significant figures. [2 marks]\n"
        "(b) Sketch a speed-time graph. [3 marks]"
    )
    payload = {
        "questions": [
            {
                "number": "1",
                "question_markdown": question_text,
                "source_pages": [99],  # Model-provided provenance must not be trusted.
                "requires_visual_context": True,
                "total_marks": None,
                "answer_requirements": [
                    {
                        "label": "(a)",
                        "marks": 2,
                        "answer_kind": "numeric",
                        "accuracy": "three significant figures",
                        "units": ["m/s"],
                        "required_tool": None,
                    },
                    {
                        "label": "(b)",
                        "marks": 3,
                        "answer_kind": "diagram",
                        "accuracy": None,
                        "units": [],
                        "required_tool": "math_plot",
                    },
                ],
            }
        ]
    }
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        response_format = body["response_format"]
        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["strict"] is True
        assert response_format["json_schema"]["name"] == "_QuestionSplitPayload"
        schema = response_format["json_schema"]["schema"]
        _assert_closed_objects(schema)
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(payload)
        return httpx.Response(
            200,
            json={
                "id": "offline-split",
                "object": "chat.completion",
                "created": 0,
                "model": "test-split-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(payload)},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    with OpenAI(
        api_key="offline-test",
        base_url="https://models.invalid/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    ) as client:
        monkeypatch.setattr(
            OpenAIChatCompletion, "_get_openai_client", lambda *_args, **_kwargs: client
        )
        # Remaining required settings come from the isolated test environment.
        overrides: dict[str, Any] = {"llm_api_key": "offline-test", "paper_split_max_attempts": 1}
        settings = Settings(**overrides)
        service = PaperAnswerService(
            settings, subject_context(settings), rag=object(), catalog_loader=lambda _: []
        )
        [question] = service.split_questions(
            format_physical_page_markdown([(2, question_text)]), unit_code="P1"
        )

    assert len(requests) == 1
    assert question["question_markdown"] == question_text.removeprefix("1 ")
    assert question["source_pages"] == [2]
    assert question["requires_visual_context"] is False
    assert question["total_marks"] == 5
    assert question["answer_requirements"] == payload["questions"][0]["answer_requirements"]
    assert question["source_kind"] == "primary"
    assert question["source_digest"]


@pytest.mark.parametrize("requirements", [{}, {"answer_requirements": None}])
def test_split_optional_fields_keep_downstream_defaults(requirements: dict[str, Any]) -> None:
    payload = _QuestionSplitPayload.model_validate(
        {"questions": [{"number": "1", "question_markdown": "Find x.", **requirements}]}
    )
    [question] = payload.model_dump(mode="json")["questions"]
    spec = question_spec_from_item(question)
    assert spec.subparts == ()
    assert spec.total_marks is None
    assert question["source_pages"] == []
    assert question["requires_visual_context"] is False


def test_split_reuses_requirement_normalization_and_nullable_fields() -> None:
    payload = _QuestionSplitPayload.model_validate(
        {
            "questions": [
                {
                    "number": "1",
                    "question_markdown": "Sketch a graph.",
                    "source_pages": None,
                    "requires_visual_context": None,
                    "total_marks": None,
                    "answer_requirements": [
                        {
                            "label": "  ",
                            "marks": 3,
                            "answer_kind": "math_plot",
                            "units": [" m ", "m", ""],
                            "required_tool": "math_plot",
                        },
                        {"label": "(b)", "marks": None, "accuracy": None},
                        {},
                    ],
                }
            ]
        }
    )
    [question] = payload.model_dump(mode="json")["questions"]
    spec = question_spec_from_item(question)
    assert question["source_pages"] is None
    assert question["requires_visual_context"] is None
    assert spec.subparts[0].label == "whole"
    assert spec.subparts[0].answer_kind == "diagram"
    assert spec.subparts[0].accuracy is None
    assert spec.subparts[0].units == ("m",)
    assert spec.subparts[1].marks is None
    assert spec.subparts[2].answer_kind == "text"
    assert spec.subparts[2].required_tool is None
    assert spec.total_marks is None


@pytest.mark.parametrize("level", ["payload", "question", "requirement"])
def test_split_rejects_unknown_fields_at_every_object_level(level: str) -> None:
    payload: dict[str, Any] = {
        "questions": [{"number": "1", "question_markdown": "Find x.", "answer_requirements": [{}]}]
    }
    invalid = deepcopy(payload)
    target = invalid
    if level != "payload":
        target = invalid["questions"][0]
    if level == "requirement":
        target = target["answer_requirements"][0]
    target["unexpected"] = "must not be silently dropped"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        _QuestionSplitPayload.model_validate(invalid)
