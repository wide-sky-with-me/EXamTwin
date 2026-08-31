from __future__ import annotations

import ast
import json
import re
from typing import Any

from llama_index.core.agent.react.types import (
    ActionReasoningStep,
    ResponseReasoningStep,
)
from llama_index.core.tools import BaseTool

from examtwin.assessment.answering_agent.finalization import (
    AgentFinalPayload,
    citation_ids_in_markdown,
)
from examtwin.platform.model_json import parse_json_response

_ACTION_MARKER = re.compile(r"(?im)^[ \t]*Action[ \t]*:[ \t]*")
_ACTION_INPUT_MARKER = re.compile(r"(?im)^[ \t]*Action Input[ \t]*:[ \t]*")
_ANSWER_MARKER = re.compile(r"(?im)^[ \t]*Answer[ \t]*:")


def _balanced_json_objects(text: str) -> list[str]:
    """Return balanced JSON-looking objects without interpreting text in strings."""

    objects: list[str] = []
    for start, char in enumerate(text):
        if char != "{":
            continue
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            current = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
            elif current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    objects.append(text[start : index + 1])
                    break
    return objects


def _parse_mapping(text: str) -> dict[str, Any] | None:
    for candidate in _balanced_json_objects(text):
        try:
            value = parse_json_response(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            return value

    stripped = text.strip()
    if not stripped:
        return {}
    try:
        literal = ast.literal_eval(stripped)
    except (SyntaxError, ValueError):
        literal = None
    if isinstance(literal, dict):
        return literal

    if stripped.startswith("(") and stripped.endswith(")"):
        stripped = stripped[1:-1].strip()
    try:
        call = ast.parse(f"_tool({stripped})", mode="eval").body
        if not isinstance(call, ast.Call) or call.args:
            return None
        return {
            keyword.arg: ast.literal_eval(keyword.value)
            for keyword in call.keywords
            if keyword.arg is not None
        }
    except (SyntaxError, ValueError):
        return None


def _infer_tool_name(
    action_input: dict[str, Any],
    by_name: dict[str, BaseTool],
) -> str | None:
    candidates: list[str] = []
    provided = set(action_input)
    for name, tool in by_name.items():
        schema = tool.metadata.fn_schema
        if schema is None:
            continue
        fields = set(schema.model_fields)
        required = {
            field_name for field_name, field in schema.model_fields.items() if field.is_required()
        }
        if provided <= fields and required <= provided:
            candidates.append(name)
    return candidates[0] if len(candidates) == 1 else None


def _action_from_object(
    value: dict[str, Any],
    by_name: dict[str, BaseTool],
) -> tuple[str, dict[str, Any]] | None:
    name = next(
        (
            str(value[key]).strip()
            for key in ("action", "tool", "tool_name", "name")
            if isinstance(value.get(key), str) and str(value[key]).strip()
        ),
        None,
    )
    if name:
        raw_input = next(
            (
                value[key]
                for key in ("action_input", "arguments", "parameters", "input")
                if key in value
            ),
            None,
        )
        if raw_input is None:
            action_input = {
                key: item
                for key, item in value.items()
                if key not in {"action", "tool", "tool_name", "name"}
            }
        elif isinstance(raw_input, dict):
            action_input = raw_input
        elif isinstance(raw_input, str):
            action_input = _parse_mapping(raw_input)
        else:
            action_input = None
        if action_input is not None:
            return name, action_input

    inferred = _infer_tool_name(value, by_name)
    return (inferred, value) if inferred else None


def _compatible_action_step(
    text: str,
    by_name: dict[str, BaseTool],
) -> ActionReasoningStep | None:
    """Normalize common single-tool ReAct variants without retaining model reasoning."""

    markers = list(_ACTION_MARKER.finditer(text))
    segments = [
        text[
            marker.end() : markers[index + 1].start() if index + 1 < len(markers) else None
        ].strip()
        for index, marker in enumerate(markers)
    ]
    for index, segment in enumerate(segments):
        first_line = segment.splitlines()[0].strip() if segment else ""
        object_value = _parse_mapping(segment) if first_line.startswith("{") else None
        if object_value is not None:
            parsed = _action_from_object(object_value, by_name)
            if parsed is not None:
                name, action_input = parsed
                return ActionReasoningStep(
                    thought="Tool call normalized.",
                    action=name,
                    action_input=action_input,
                )
            continue

        name_match = re.match(r"`?([A-Za-z_][\w.-]*)`?(.*)", first_line)
        if not name_match:
            continue
        name = name_match.group(1)
        if name not in by_name:
            continue
        inline_input = name_match.group(2).strip()
        action_input = _parse_mapping(inline_input) if inline_input else None
        input_match = _ACTION_INPUT_MARKER.search(segment)
        if input_match:
            action_input = _parse_mapping(segment[input_match.end() :])
        if (
            action_input is None
            and index + 1 < len(segments)
            and segments[index + 1].lstrip().startswith("{")
        ):
            action_input = _parse_mapping(segments[index + 1])
        if action_input is not None:
            return ActionReasoningStep(
                thought="Tool call normalized.",
                action=name,
                action_input=action_input,
            )
    return None


def _validated_final_json(text: str) -> str | None:
    """Recover only the declared final payload, never surrounding reasoning text."""

    for candidate in reversed(_balanced_json_objects(text)):
        try:
            payload = AgentFinalPayload.model_validate(parse_json_response(candidate))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        return payload.model_dump_json()
    return None


def _recovered_plain_answer(
    text: str,
    step: ResponseReasoningStep,
    *,
    grounded: bool,
) -> str | None:
    if not _ANSWER_MARKER.search(text):
        return None
    answer = step.response.strip()
    if not answer or "{" in answer:
        return None
    try:
        payload = AgentFinalPayload(
            answer_markdown=answer,
            citation_ids=citation_ids_in_markdown(answer),
            confidence=0.5,
            grounded=grounded,
            warnings=["Final answer was recovered from a non-JSON response."],
        )
    except ValueError:
        return None
    return payload.model_dump_json()
