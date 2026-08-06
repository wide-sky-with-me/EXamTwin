from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel

_JSON_AMBIGUOUS_LATEX_COMMANDS = {
    "bar",
    "begin",
    "beta",
    "bf",
    "binom",
    "frac",
    "forall",
    "ne",
    "neq",
    "nabla",
    "not",
    "ref",
    "rho",
    "right",
    "rm",
    "tan",
    "tau",
    "text",
    "textbf",
    "theta",
    "times",
    "tt",
}
# A raw ``\nu`` is indistinguishable from a valid JSON newline followed by ``u``.
# Standards-compliant providers must encode Greek nu as ``\\nu``; preserving JSON
# newlines takes precedence so equation lines beginning with ``u_n`` are not corrupted.
_MATH_SPAN = re.compile(
    r"(?P<delimiter>\${1,2})(?P<body>.*?)(?P=delimiter)",
    re.DOTALL,
)
_MISSING_LATEX_COMMAND = re.compile(
    r"(?<!\\)\b("
    r"binom|cdot|dfrac|frac|geq|lambda|ldots|leq|neq|pm|sim|sqrt|text|times"
    r")(?=\s*(?:[{(]|\b))"
)
StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


def _repair_json_backslashes(text: str) -> str:
    """Escape LaTeX backslashes inside JSON strings without changing JSON escapes."""
    repaired: list[str] = []
    in_string = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == '"':
            in_string = not in_string
            repaired.append(char)
            index += 1
            continue
        if not in_string or char != "\\":
            repaired.append(char)
            index += 1
            continue
        if index + 1 >= len(text):
            repaired.append("\\\\")
            index += 1
            continue

        escaped = text[index + 1]
        if escaped in {'"', "\\", "/"}:
            repaired.extend((char, escaped))
            index += 2
            continue
        if escaped == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", text[index + 2 : index + 6]):
            repaired.append(text[index : index + 6])
            index += 6
            continue
        if escaped in {"b", "f", "n", "r", "t"}:
            command_match = re.match(r"[A-Za-z]+", text[index + 1 :])
            command = command_match.group(0).lower() if command_match else ""
            if command not in _JSON_AMBIGUOUS_LATEX_COMMANDS:
                repaired.extend((char, escaped))
                index += 2
                continue

        repaired.append("\\\\")
        index += 1
    return "".join(repaired)


def parse_json_response(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    if start < 0:
        raise ValueError("Model did not return a JSON object")
    repaired = _repair_json_backslashes(stripped[start:])
    payload, _end = json.JSONDecoder().raw_decode(repaired)
    if not isinstance(payload, dict):
        raise ValueError("Model did not return a JSON object")
    return payload


def repair_markdown_latex(markdown: str) -> str:
    """Repair common LaTeX commands stripped by non-compliant JSON providers."""

    def repair_span(match: re.Match[str]) -> str:
        delimiter = match.group("delimiter")
        body = _MISSING_LATEX_COMMAND.sub(r"\\\1", match.group("body"))
        body = re.sub(
            r"\\binom\(\s*([^,()]+)\s*,\s*([^,()]+)\s*\)",
            r"\\binom{\1}{\2}",
            body,
        )
        return f"{delimiter}{body}{delimiter}"

    return _MATH_SPAN.sub(repair_span, markdown)


def validate_structured_response(
    response: Any,
    model: type[StructuredModel],
    *,
    allow_reasoning_content: bool = False,
) -> StructuredModel:
    """Validate a LiteLLM/OpenAI-style response while preserving raw LaTeX."""

    choices = getattr(response, "choices", None)
    if not choices:
        raise ValueError("Structured provider returned no choices")
    message: Any = choices[0].message
    content = getattr(message, "content", None)
    content_error: Exception | None = None
    if isinstance(content, str) and content.strip():
        try:
            return model.model_validate(parse_json_response(content))
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            content_error = error

    parsed = getattr(message, "parsed", None)
    if isinstance(parsed, model):
        return parsed
    if parsed is not None:
        return model.model_validate(parsed)
    if allow_reasoning_content:
        reasoning_content = getattr(message, "reasoning_content", None)
        if isinstance(reasoning_content, str) and reasoning_content.strip():
            return model.model_validate(parse_json_response(reasoning_content))
    if content_error is not None:
        raise content_error
    raise ValueError("Structured provider returned no usable payload")
