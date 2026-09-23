from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from examtwin.assessment.answering_agent.contracts import (
    AgentEventSink,
    AgentRunLedger,
    QuestionImage,
)
from examtwin.assessment.answering_agent.finalization import citation_ids_in_markdown
from examtwin.assessment.answering_agent.host_capabilities import (
    answer_artifact_capabilities,
)
from examtwin.assessment.paper_parsing import (
    QuestionSourcePageResolutionError,
    QuestionSourceStructureError,
    question_has_unresolved_source_placeholder,
    question_spec_from_item,
    reconcile_question_source_pages,
    upload_to_markdown,
    validate_question_source_structure,
)
from examtwin.assessment.rag import RagService
from examtwin.contracts.evidence import Citation, SubpartRequirement
from examtwin.contracts.knowledge import AskRequest
from examtwin.contracts.papers import (
    PaperAnswerResponse,
    PaperKnowledgeReference,
    PaperQuestionAnswer,
)
from examtwin.knowledge.public import (
    KnowledgeRepository,
    list_knowledge_points,
    parse_exam_identity,
)
from examtwin.platform.agent_runtime.model import HarnessMessage
from examtwin.platform.agent_runtime.structured import (
    StructuredModelPort,
    StructuredTask,
    StructuredTaskRunner,
)
from examtwin.platform.config import Settings
from examtwin.platform.providers import required_secret
from examtwin.platform.structured_model import LiteLLMStructuredModel
from examtwin.subjects.public import SubjectContext

logger = logging.getLogger(__name__)

SPLIT_CONTRACT_VERSION = "paper-question-split-v12"

PAGE_SECTION = re.compile(
    r"(?=<!--\s*(?:pages?\s+\d+|examtwin:physical-page=\d+))",
    re.IGNORECASE,
)
_SUBPART_LINE = re.compile(
    r"(?im)^[ \t]*(?:#{1,6}[ \t]*)?(?:\*{1,2})?(?:\d+[ \t]+)?"
    r"(?P<label>\([a-zivx]+\)(?:[ \t]*\([a-zivx]+\))*)"
    r"(?:\*{1,2})?(?=[ \t.:]|$)"
)
_PROOF_DIRECTIVE = re.compile(
    r"\b(?:show\s+that|prove(?:\s+that)?|demonstrate\s+that|verify\s+that)\b",
    re.IGNORECASE,
)
_QUESTION_ALIAS_TEXT = re.compile(r"[^a-z0-9]+")
_MARK_ANNOTATION = re.compile(
    r"(?:(?:\*\*|__)\s*)?\[\s*\d+\s*marks?\s*\](?:\s*(?:\*\*|__))?",
    re.IGNORECASE,
)
_QUESTION_NUMBER_ALIAS_MIN_CHARS = 120
_QUESTION_NUMBER_ALIAS_MIN_SIMILARITY = 0.96
_QUESTION_NUMBER_PARTIAL_MIN_CHARS = 500
_QUESTION_NUMBER_PARTIAL_MIN_SIMILARITY = 0.84

SplitCheckpointLoader = Callable[[int, str], list[dict[str, Any]] | None]
SplitCheckpointSaver = Callable[[int, int, str, list[dict[str, Any]], float], None]


class _QuestionRepairGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: str = Field(min_length=1, max_length=32)
    candidate_indexes: list[int] = Field(min_length=1)
    preferred_candidate_index: int | None = Field(default=None, ge=0)


class _QuestionRepairPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    groups: list[_QuestionRepairGroup] = Field(min_length=1)


class _QuestionSplitRequirement(SubpartRequirement):
    model_config = ConfigDict(extra="forbid")


class _QuestionSplitItem(BaseModel):
    """Typed provider payload; provenance is still established by the source gates."""

    model_config = ConfigDict(extra="forbid")

    number: str
    question_markdown: str
    source_pages: list[int] | None = Field(default_factory=list)
    requires_visual_context: bool | None = False
    total_marks: int | None = Field(default=None, ge=0, le=200)
    answer_requirements: list[_QuestionSplitRequirement] | None = Field(default_factory=list)


class _QuestionSplitPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[_QuestionSplitItem]


class _QuestionCandidateConflict(ValueError):
    """A same-source overlap conflict that may be resolved against the trusted source."""

    def __init__(self, message: str, *, question_numbers: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.question_numbers = question_numbers


def _build_question_repair_model(settings: Settings) -> StructuredModelPort:
    api_key = settings.llm_api_key
    if api_key is None:
        raise RuntimeError("Question structure repair requires LLM_API_KEY")
    return LiteLLMStructuredModel(
        model=settings.paper_split_model,
        provider=settings.litellm_provider,
        api_base=settings.llm_base_url,
        api_key=api_key.get_secret_value(),
        reasoning_effort=settings.paper_split_reasoning_effort,
    )


def _build_question_split_model(settings: Settings) -> StructuredModelPort:
    return LiteLLMStructuredModel(
        model=settings.paper_split_model,
        provider=settings.litellm_provider,
        api_base=settings.llm_base_url,
        api_key=required_secret(settings.llm_api_key),
        reasoning_effort=settings.paper_split_reasoning_effort,
        max_retries=1,
    )


def _split_markdown_batches(
    markdown: str,
    *,
    max_chars: int,
    overlap_max_chars: int = 4_000,
) -> list[str]:
    if len(markdown) <= max_chars:
        return [markdown]
    sections = [item for item in PAGE_SECTION.split(markdown) if item.strip()]
    if len(sections) == 1:
        overlap = min(overlap_max_chars, max_chars // 10)
        return [
            markdown[max(0, start - overlap) : start + max_chars]
            for start in range(0, len(markdown), max_chars - overlap)
        ]

    batches: list[str] = []
    current: list[str] = []
    current_size = 0
    for section in sections:
        if current and current_size + len(section) > max_chars:
            batches.append("".join(current))
            current = [current[-1], section]
            current_size = sum(len(item) for item in current)
        else:
            current.append(section)
            current_size += len(section)
    if current:
        batches.append("".join(current))
    return batches


def _question_number_identity(number: str) -> tuple[str, str | None, bool]:
    compact = re.sub(r"\s+", "", number).lower()
    exact = re.fullmatch(r"0*(\d+)", compact)
    if exact:
        canonical = str(int(exact.group(1)))
        return compact, canonical, True
    prefix = re.match(r"0*(\d+)", compact)
    canonical = str(int(prefix.group(1))) if prefix else None
    return compact, canonical, False


def _normalized_subpart_label(label: object) -> str:
    normalized = re.sub(r"\s+", "", str(label)).lower()
    wrapped_decimal = re.fullmatch(r"\(0*\d+\.(\d+)\)", normalized)
    if wrapped_decimal:
        return f".{int(wrapped_decimal.group(1))}"
    return re.sub(r"^\d+(?=[.(])", "", normalized)


def _candidate_sections(item: dict[str, Any]) -> tuple[str, dict[str, str]]:
    text = str(item.get("question_markdown", "")).strip()
    expected = {
        normalized
        for requirement in item.get("answer_requirements") or []
        if isinstance(requirement, dict)
        and (normalized := _normalized_subpart_label(requirement.get("label", "")))
        and normalized != "whole"
    }
    matches = []
    for match in _SUBPART_LINE.finditer(text):
        label = _normalized_subpart_label(match.group("label"))
        if (
            not expected
            or label in expected
            or any(expected_label.startswith(label) for expected_label in expected)
        ):
            matches.append(match)
    if not matches:
        return text, {}
    stem = text[: matches[0].start()].strip()
    if re.fullmatch(
        rf"(?:question\s*)?{re.escape(str(item.get('number', '')).strip())}[\s.:]*",
        stem,
        re.IGNORECASE,
    ):
        stem = ""
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        label = _normalized_subpart_label(match.group("label"))
        section = text[match.start() : end].strip()
        current = sections.get(label)
        if current is None or len(section) > len(current):
            sections[label] = section
    return stem, sections


def _merge_compatible_source_text(current: str, candidate: str, *, field: str) -> str:
    if not current:
        return candidate
    if not candidate:
        return current
    normalized_current = re.sub(r"\s+", " ", current).strip()
    normalized_candidate = re.sub(r"\s+", " ", candidate).strip()
    if normalized_current == normalized_candidate:
        return current
    annotation_free_current = re.sub(
        r"\s+",
        " ",
        _MARK_ANNOTATION.sub("", current),
    ).strip()
    annotation_free_candidate = re.sub(
        r"\s+",
        " ",
        _MARK_ANNOTATION.sub("", candidate),
    ).strip()
    if annotation_free_current == annotation_free_candidate:
        current_annotations = len(_MARK_ANNOTATION.findall(current))
        candidate_annotations = len(_MARK_ANNOTATION.findall(candidate))
        return candidate if candidate_annotations > current_annotations else current
    if normalized_candidate.startswith(normalized_current):
        return candidate
    if normalized_current.startswith(normalized_candidate):
        return current
    raise _QuestionCandidateConflict(f"同题号主源{field}冲突，不能按文本长度择优")


def _without_split_metadata(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if not key.startswith("_split_")}


def _requirement_map(item: dict[str, Any]) -> dict[str, dict[str, Any]]:
    requirements: dict[str, dict[str, Any]] = {}
    for requirement in item.get("answer_requirements") or []:
        if not isinstance(requirement, dict):
            continue
        label = _normalized_subpart_label(requirement.get("label", ""))
        if label:
            requirements[label] = requirement
    return requirements


def _requirements_compatible(
    narrower: dict[str, dict[str, Any]],
    broader: dict[str, dict[str, Any]],
) -> bool:
    for label, requirement in narrower.items():
        other = broader[label]
        for key in requirement.keys() | other.keys():
            if key == "label":
                continue
            value = requirement.get(key)
            other_value = other.get(key)
            if (
                value not in (None, "", [])
                and other_value not in (None, "", [])
                and value != other_value
            ):
                return False
    return True


def _drop_structurally_dominated_candidates(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    requirement_maps = [_requirement_map(item) for item in candidates]

    def text_is_contained(index: int, other_index: int) -> bool:
        item = candidates[index]
        other = candidates[other_index]
        text = _QUESTION_ALIAS_TEXT.sub(
            "",
            _MARK_ANNOTATION.sub("", str(item.get("question_markdown", ""))).lower(),
        )
        other_text = _QUESTION_ALIAS_TEXT.sub(
            "",
            _MARK_ANNOTATION.sub("", str(other.get("question_markdown", ""))).lower(),
        )
        if len(text) < 60 or text == other_text or text not in other_text:
            return False

        item_pages = {int(page) for page in item.get("source_pages") or []}
        other_pages = {int(page) for page in other.get("source_pages") or []}
        if item_pages and other_pages and not item_pages <= other_pages:
            return False
        item_marks = item.get("total_marks")
        other_marks = other.get("total_marks")
        if (
            isinstance(item_marks, int)
            and not isinstance(item_marks, bool)
            and isinstance(other_marks, int)
            and not isinstance(other_marks, bool)
            and item_marks > other_marks
        ):
            return False

        requirements = requirement_maps[index]
        other_requirements = requirement_maps[other_index]
        common_labels = requirements.keys() & other_requirements.keys()
        if common_labels and not _requirements_compatible(
            {label: requirements[label] for label in common_labels},
            {label: other_requirements[label] for label in common_labels},
        ):
            return False
        return True

    retained: list[dict[str, Any]] = []
    for index, item in enumerate(candidates):
        requirements = requirement_maps[index]
        dominated = any(
            (
                bool(requirements)
                and requirements.keys() < other.keys()
                and _requirements_compatible(requirements, other)
            )
            or text_is_contained(index, other_index)
            for other_index, other in enumerate(requirement_maps)
            if other_index != index
        )
        if not dominated:
            retained.append(item)
    return retained


def _align_primary_question_numbers_from_recovery(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Correct a truncated primary number only when recovery gives unique strong proof.

    Visual review remains authoritative for wording. The PDF text layer may only supply a
    different top-level number when a near-identical, equal-mark recovery candidate exists;
    ambiguous or short matches are left unchanged for the normal fail-closed repair path.
    """

    aligned = [dict(item) for item in items]
    primary_texts_by_number: dict[str, list[str]] = {}
    all_numbers: set[str] = set()
    for item in aligned:
        _compact, canonical, is_top_level = _question_number_identity(
            str(item.get("number", "?")).strip()
        )
        if not canonical or not is_top_level:
            continue
        all_numbers.add(canonical)
        if item.get("_split_source", "primary") != "recovery":
            primary_texts_by_number.setdefault(canonical, []).append(
                _QUESTION_ALIAS_TEXT.sub(
                    "",
                    str(item.get("question_markdown", "")).lower(),
                )
            )

    def neighbor_score(number: str) -> int:
        if not number.isdigit():
            return 0
        value = int(number)
        return int(str(value - 1) in all_numbers) + int(str(value + 1) in all_numbers)

    recovery: list[tuple[dict[str, Any], str, str]] = []
    for item in aligned:
        if item.get("_split_source") != "recovery":
            continue
        _compact, canonical, is_top_level = _question_number_identity(
            str(item.get("number", "?")).strip()
        )
        text = _QUESTION_ALIAS_TEXT.sub(
            "",
            str(item.get("question_markdown", "")).lower(),
        )
        if canonical and is_top_level and len(text) >= _QUESTION_NUMBER_ALIAS_MIN_CHARS:
            recovery.append((item, canonical, text))

    for index, item in enumerate(aligned):
        if item.get("_split_source", "primary") == "recovery":
            continue
        _compact, canonical, is_top_level = _question_number_identity(
            str(item.get("number", "?")).strip()
        )
        primary_text = _QUESTION_ALIAS_TEXT.sub(
            "",
            str(item.get("question_markdown", "")).lower(),
        )
        if (
            not canonical
            or not is_top_level
            or len(primary_text) < _QUESTION_NUMBER_ALIAS_MIN_CHARS
        ):
            continue

        primary_marks = item.get("total_marks")
        matches: list[tuple[float, dict[str, Any], str]] = []
        for recovery_item, recovery_number, recovery_text in recovery:
            if recovery_number == canonical:
                continue
            recovery_marks = recovery_item.get("total_marks")
            marks_match = not (
                isinstance(primary_marks, int)
                and not isinstance(primary_marks, bool)
                and isinstance(recovery_marks, int)
                and not isinstance(recovery_marks, bool)
                and primary_marks != recovery_marks
            )
            similarity = SequenceMatcher(None, primary_text, recovery_text).ratio()
            partial_overlap = (
                min(len(primary_text), len(recovery_text)) >= _QUESTION_NUMBER_PARTIAL_MIN_CHARS
                and similarity >= _QUESTION_NUMBER_PARTIAL_MIN_SIMILARITY
            )
            if (
                marks_match and similarity >= _QUESTION_NUMBER_ALIAS_MIN_SIMILARITY
            ) or partial_overlap:
                matches.append((similarity, recovery_item, recovery_number))

        target_numbers = {number for _similarity, _candidate, number in matches}
        if len(target_numbers) != 1:
            continue
        _similarity, witness, target_number = max(matches, key=lambda match: match[0])
        same_number_texts = primary_texts_by_number.get(canonical, [])
        has_distinct_collision = any(
            other != primary_text and SequenceMatcher(None, primary_text, other).ratio() < 0.5
            for other in same_number_texts
        )
        target_fills_collision_gap = (
            has_distinct_collision and target_number not in primary_texts_by_number
        )
        target_has_stronger_sequence = neighbor_score(target_number) > neighbor_score(canonical)
        if not target_fills_collision_gap and not target_has_stronger_sequence:
            continue
        corrected = dict(item)
        corrected["number"] = str(witness.get("number") or target_number).strip()
        aligned[index] = corrected
    return aligned


def _drop_covered_recovery_fragments(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Discard lower-authority decimal subparts already present in a primary question.

    PDF text recovery occasionally flattens ``12.1`` to ``121`` and emits it as a new
    top-level question. Only discard such a candidate when the longest primary-number
    prefix exists, the flattened number is not itself a primary question, and the
    recovery wording is strongly covered by that primary question.
    """

    primary_by_number: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        if item.get("_split_source", "primary") == "recovery":
            continue
        _compact, canonical, is_top_level = _question_number_identity(
            str(item.get("number", "?")).strip()
        )
        if canonical and is_top_level:
            primary_by_number.setdefault(canonical, []).append(item)

    retained: list[dict[str, Any]] = []
    for item in items:
        if item.get("_split_source") != "recovery":
            retained.append(item)
            continue
        compact, canonical, is_top_level = _question_number_identity(
            str(item.get("number", "?")).strip()
        )
        if not canonical or not is_top_level or canonical in primary_by_number:
            retained.append(item)
            continue
        prefix = max(
            (
                number
                for number in primary_by_number
                if compact.startswith(number)
                and len(compact) == len(number) + 1
                and compact[-1] != "0"
            ),
            key=len,
            default="",
        )
        if not prefix:
            retained.append(item)
            continue

        recovery_text = _QUESTION_ALIAS_TEXT.sub(
            "",
            _MARK_ANNOTATION.sub("", str(item.get("question_markdown", ""))).lower(),
        )
        recovery_marks = item.get("total_marks")
        covered = False
        if len(recovery_text) >= 120:
            for primary in primary_by_number[prefix]:
                primary_marks = primary.get("total_marks")
                if (
                    isinstance(recovery_marks, int)
                    and not isinstance(recovery_marks, bool)
                    and isinstance(primary_marks, int)
                    and not isinstance(primary_marks, bool)
                    and recovery_marks > primary_marks
                ):
                    continue
                primary_text = _QUESTION_ALIAS_TEXT.sub(
                    "",
                    _MARK_ANNOTATION.sub("", str(primary.get("question_markdown", ""))).lower(),
                )
                matched = sum(
                    block.size
                    for block in SequenceMatcher(
                        None,
                        recovery_text,
                        primary_text,
                        autojunk=False,
                    ).get_matching_blocks()
                )
                if matched / len(recovery_text) >= 0.9:
                    covered = True
                    break
        if not covered:
            retained.append(item)
    return retained


def _merge_top_level_candidates(
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    primary = [item for item in candidates if item.get("_split_source", "primary") != "recovery"]
    trusted = primary or candidates
    trusted = sorted(
        trusted,
        key=lambda item: int(item.get("_split_batch_index", 0)),
    )
    source_digests = {
        str(item["_split_source_digest"]) for item in trusted if item.get("_split_source_digest")
    }
    if len(source_digests) > 1:
        raise ValueError("同题号候选来自不同主源，禁止跨来源合并")
    trusted = _drop_structurally_dominated_candidates(trusted)
    repaired = _without_split_metadata(dict(trusted[0]))
    repaired.pop("source_pages", None)

    stem = ""
    sections: dict[str, str] = {}
    section_order: list[str] = []
    requirements: dict[str, dict[str, Any]] = {}
    requirement_order: list[str] = []
    knowledge_codes: list[str] = []
    for item in trusted:
        candidate_stem, candidate_sections = _candidate_sections(item)
        stem = _merge_compatible_source_text(stem, candidate_stem, field="题干")
        for label, section in candidate_sections.items():
            if label not in sections:
                section_order.append(label)
                sections[label] = section
            else:
                sections[label] = _merge_compatible_source_text(
                    sections[label],
                    section,
                    field=f"子问 {label}",
                )
        for requirement in item.get("answer_requirements") or []:
            if not isinstance(requirement, dict):
                continue
            label = _normalized_subpart_label(requirement.get("label", ""))
            if not label:
                continue
            if label not in requirements:
                requirement_order.append(label)
                requirements[label] = {**requirement, "label": label}
                continue
            current = requirements[label]
            for key, value in requirement.items():
                if current.get(key) in (None, "", []) and value not in (None, "", []):
                    current[key] = value
                elif (
                    value not in (None, "", [])
                    and current.get(key) not in (None, "", [])
                    and current[key] != value
                ):
                    if (
                        key == "answer_kind"
                        and "proof" in {str(current[key]), str(value)}
                        and _PROOF_DIRECTIVE.search(sections.get(label, ""))
                    ):
                        current[key] = "proof"
                        continue
                    raise _QuestionCandidateConflict(f"同题号主源子问 {label} 的 {key} 冲突")
        for code in item.get("knowledge_codes") or []:
            normalized_code = str(code).strip()
            if normalized_code and normalized_code not in knowledge_codes:
                knowledge_codes.append(normalized_code)

    text_parts = [stem, *(sections[label] for label in section_order)]
    repaired["question_markdown"] = "\n\n".join(part for part in text_parts if part).strip()
    if requirements:
        repaired_requirements = [requirements[label] for label in requirement_order]
        repaired["answer_requirements"] = repaired_requirements
        raw_marks = [requirement.get("marks") for requirement in repaired_requirements]
        marks = [mark for mark in raw_marks if isinstance(mark, int) and not isinstance(mark, bool)]
        repaired["total_marks"] = sum(marks) if raw_marks and len(marks) == len(raw_marks) else None
    if knowledge_codes:
        repaired["knowledge_codes"] = knowledge_codes
    return repaired


def _merge_split_questions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    identities = [_question_number_identity(str(item.get("number", "?")).strip()) for item in items]
    top_level_numbers = {
        canonical
        for _compact, canonical, is_top_level in identities
        if canonical is not None and is_top_level
    }
    groups: list[list[tuple[dict[str, Any], bool]]] = []
    positions: dict[str, int] = {}
    for item, (compact, canonical, is_top_level) in zip(items, identities, strict=True):
        key = canonical if canonical in top_level_numbers else compact
        if not key or key == "?" or key not in positions:
            if key and key != "?":
                positions[key] = len(groups)
            groups.append([(item, is_top_level)])
            continue
        groups[positions[key]].append((item, is_top_level))

    merged: list[dict[str, Any]] = []
    for group in groups:
        top_level = [item for item, is_top_level in group if is_top_level]
        if top_level:
            try:
                repaired = _merge_top_level_candidates(top_level)
            except _QuestionCandidateConflict as error:
                number = str(group[0][0].get("number", "?")).strip() or "?"
                raise _QuestionCandidateConflict(
                    str(error),
                    question_numbers=(number,),
                ) from error
            repaired["number"] = group[0][0].get("number", repaired.get("number"))
            merged.append(repaired)
        else:
            merged.append(_without_split_metadata(group[0][0]))
    return merged


def _combine_repair_group(
    items: list[dict[str, Any]],
    group: _QuestionRepairGroup,
    *,
    preferred_item: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target_compact, target_canonical, _target_is_top_level = _question_number_identity(group.number)
    identities = [_question_number_identity(str(item.get("number", "?")).strip()) for item in items]
    if target_canonical is not None:
        identity_matches = any(canonical == target_canonical for _, canonical, _ in identities)
    else:
        identity_matches = any(compact == target_compact for compact, _, _ in identities)
    if not identity_matches:
        raise ValueError(f"结构修复模型为题组生成了无来源题号：{group.number}")

    exact_top_level = [
        item
        for item, (compact, canonical, is_top_level) in zip(items, identities, strict=True)
        if is_top_level
        and (
            canonical == target_canonical
            if target_canonical is not None
            else compact == target_compact
        )
    ]
    if preferred_item is not None:
        preferred_identity = _question_number_identity(
            str(preferred_item.get("number", "?")).strip()
        )
        preferred_compact, preferred_canonical, preferred_is_top_level = preferred_identity
        preferred_matches = (
            preferred_canonical == target_canonical
            if target_canonical is not None
            else preferred_compact == target_compact
        )
        if not preferred_matches or (exact_top_level and not preferred_is_top_level):
            raise ValueError(f"结构修复模型为第 {group.number} 题选择了不匹配的权威候选")

    if preferred_item is not None:
        repaired = _without_split_metadata(dict(preferred_item))
        repaired.pop("source_pages", None)
    elif exact_top_level:
        repaired = _merge_top_level_candidates(exact_top_level)
    else:
        repaired = dict(items[0])
        texts = list(
            dict.fromkeys(
                text for item in items if (text := str(item.get("question_markdown", "")).strip())
            )
        )
        repaired["question_markdown"] = "\n\n".join(texts)

    repaired["number"] = group.number.strip()
    repaired.pop("source_pages", None)
    repaired["requires_visual_context"] = any(
        bool(item.get("requires_visual_context")) for item in items
    )

    ordered_items = (
        [preferred_item, *(item for item in items if item is not preferred_item)]
        if preferred_item is not None
        else items
    )
    preferred_labels = (
        {
            _normalized_subpart_label(requirement.get("label", ""))
            for requirement in preferred_item.get("answer_requirements") or []
            if isinstance(requirement, dict)
            and _normalized_subpart_label(requirement.get("label", ""))
        }
        if preferred_item is not None
        else set()
    )
    knowledge_codes: list[str] = []
    requirements: list[Any] = []
    requirement_keys: set[str] = set()
    requirements_by_label: dict[str, dict[str, Any]] = {}
    for item in ordered_items:
        for code in item.get("knowledge_codes") or []:
            normalized_code = str(code).strip()
            if normalized_code and normalized_code not in knowledge_codes:
                knowledge_codes.append(normalized_code)
        for requirement in item.get("answer_requirements") or []:
            if preferred_item is not None and isinstance(requirement, dict):
                label = _normalized_subpart_label(requirement.get("label", ""))
                if not label:
                    continue
                if preferred_labels and label not in preferred_labels:
                    continue
                current = requirements_by_label.get(label)
                if current is None:
                    normalized = {**requirement, "label": label}
                    requirements_by_label[label] = normalized
                    requirements.append(normalized)
                    continue
                for key, value in requirement.items():
                    if key == "label":
                        continue
                    if current.get(key) in (None, "", []) and value not in (None, "", []):
                        current[key] = value
                continue
            key = json.dumps(requirement, ensure_ascii=False, sort_keys=True)
            if key not in requirement_keys:
                requirement_keys.add(key)
                requirements.append(requirement)
    if preferred_item is not None and any(
        isinstance(requirement, dict)
        and _normalized_subpart_label(requirement.get("label", "")) != "whole"
        for requirement in requirements
    ):
        requirements = [
            requirement
            for requirement in requirements
            if not isinstance(requirement, dict)
            or _normalized_subpart_label(requirement.get("label", "")) != "whole"
        ]
    if knowledge_codes:
        repaired["knowledge_codes"] = knowledge_codes
    if requirements:
        repaired["answer_requirements"] = requirements
        repaired["total_marks"] = None
    elif not exact_top_level:
        totals = [int(total) for item in items if (total := item.get("total_marks")) is not None]
        repaired["total_marks"] = max(totals, default=None)
    return repaired


def _apply_question_repair_plan(
    items: list[dict[str, Any]],
    plan: _QuestionRepairPlan,
) -> list[dict[str, Any]]:
    indexes = [index for group in plan.groups for index in group.candidate_indexes]
    if sorted(indexes) != list(range(len(items))):
        raise ValueError("结构修复模型必须将每个候选题恰好使用一次")

    group_identities: set[str] = set()
    repaired: list[dict[str, Any]] = []
    for group in plan.groups:
        if len(group.candidate_indexes) > 1 and group.preferred_candidate_index is None:
            raise ValueError(f"结构修复模型必须为第 {group.number} 题选择权威候选")
        compact, canonical, _is_top_level = _question_number_identity(group.number)
        identity = canonical or compact
        if not identity or identity in group_identities:
            raise ValueError(f"结构修复模型返回了重复或无效的顶层题号：{group.number}")
        group_identities.add(identity)
        preferred_item: dict[str, Any] | None = None
        if group.preferred_candidate_index is not None:
            if group.preferred_candidate_index not in group.candidate_indexes:
                raise ValueError(f"结构修复模型为第 {group.number} 题选择了组外候选")
            preferred_item = items[group.preferred_candidate_index]
        repaired.append(
            _combine_repair_group(
                [items[index] for index in group.candidate_indexes],
                group,
                preferred_item=preferred_item,
            )
        )
    return repaired


class PaperAnswerService:
    def __init__(
        self,
        settings: Settings,
        subject: SubjectContext,
        *,
        knowledge_repository: KnowledgeRepository | None = None,
        rag: Any | None = None,
        splitter: Callable[[str, list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
        parser: Callable[[Settings, str, bytes], str] | None = None,
        catalog_loader: Callable[[str | None], list[dict[str, Any]]] | None = None,
        structured_model: StructuredModelPort | None = None,
    ):
        self.settings = settings
        self.subject = subject
        self.knowledge_repository = knowledge_repository
        self.rag = rag or RagService(settings, subject, knowledge_repository)
        self.splitter = splitter
        self.parser = parser or upload_to_markdown
        self.catalog_loader = catalog_loader or self._load_catalog
        self.structured_model = structured_model

    def _load_catalog(self, unit_code: str | None) -> list[dict[str, Any]]:
        del unit_code
        if self.knowledge_repository is None:
            raise RuntimeError("Knowledge repository is required to load the question catalog")
        # A paper unit is not a safe knowledge boundary: synoptic papers can
        # legitimately cite objectives taught in earlier units.  Keep the
        # subject boundary here and let answer-used evidence decide which
        # knowledge cards are exposed.
        points = list_knowledge_points(
            self.knowledge_repository,
            subject_code=self.subject.subject_code,
            unit_code=None,
        )
        detailed = [
            point for point in points if point["features"].get("node_type") == "learning_objective"
        ]
        return detailed or [
            point for point in points if point["features"].get("node_type") == "topic"
        ]

    def _catalog(self, unit_code: str | None) -> list[dict[str, Any]]:
        return self.catalog_loader(unit_code)

    def _split_with_llm(
        self,
        markdown: str,
        catalog: list[dict[str, Any]],
        *,
        primary_markdown: str | None = None,
        load_checkpoint: SplitCheckpointLoader | None = None,
        save_checkpoint: SplitCheckpointSaver | None = None,
    ) -> list[dict[str, Any]]:
        del catalog
        artifact_capabilities = answer_artifact_capabilities(
            self.subject.package.require_skill().tool_names
        )
        artifact_capability_text = (
            ", ".join(f"{name} ({shape} artifact)" for name, shape in artifact_capabilities)
            or "none"
        )

        def split_batch(batch: str, source_kind: str) -> list[dict[str, Any]]:
            source_instruction = (
                "This batch is PRIMARY visually reviewed Markdown. Preserve its wording and "
                "mathematics exactly."
                if source_kind == "primary"
                else "This batch is a RECOVERY text-layer appendix. Return only questions that "
                "are genuinely absent from the primary source. Never emit placeholders such as "
                "'as printed', 'omitted', or 'not captured', and never rewrite primary content."
            )
            prompt = f"""
You extract top-level questions from a {self.subject.pack.title} examination paper.
Source authority: {source_instruction}
MinerU may omit a printed question number or place a question inside an HTML table.
Reconstruct the ordered top-level questions using surrounding numbers, mark labels,
page turns and subpart labels. Keep every subpart with its top-level question. Ignore
instructions, cover pages, examiner-use tables and blank answer lines. Do not solve.
Sections marked with physical page comments may already have been reconciled against
the page images. Treat that visually reviewed Markdown as the primary source.
The worker separates visually reviewed primary Markdown from any lower-authority PDF
text-layer recovery appendix. Never let recovery wording replace primary wording.
Before returning, verify that every visible top-level number, subpart label and mark
value in this batch appears exactly once in the resulting question list.
Each visually reviewed PDF page starts with an immutable
`<!-- examtwin:physical-page=N -->` marker. The application derives source pages from
question positions after your response, so `source_pages` is only a compatibility
field and will never be trusted as provenance.

Set `requires_visual_context` to true only when solving the question depends on a
printed figure, diagram, graph, chart, plot, shaded region, or other spatial visual
information. It must be false for text-only probability/algebra questions even though
their source PDF pages are available.
Extract an `answer_requirements` item for every visible subpart, or one item labelled
`whole` when there are no subparts. Preserve the printed subpart label and marks.
Start every printed subpart on a new line with its exact label, for example `(a)` or
`(a)(i)`. This allows deterministic repair when one question crosses batch boundaries.
`answer_kind` must be one of text, numeric, expression, proof, table, diagram, image.
Copy an explicit accuracy instruction and required units. Set `required_tool` only when
the candidate must create an answer artifact, and only to one of the current subject
capabilities listed here: {artifact_capability_text}. Use the installed subject policy to
choose among them. Merely reading a printed source figure does not require an answer artifact.

Return only:
{{
  "questions": [
    {{
      "number": "1",
      "question_markdown": "complete question with all subparts",
      "source_pages": [2, 3],
      "requires_visual_context": false,
      "total_marks": 4,
      "answer_requirements": [
        {{
          "label": "(a)",
          "marks": 2,
          "answer_kind": "numeric",
          "accuracy": "three significant figures",
          "units": [],
          "required_tool": null
        }}
      ]
    }}
  ]
}}

Paper Markdown:
{batch}
""".strip()
            split_model = _build_question_split_model(self.settings)
            last_error: Exception | None = None
            for attempt in range(1, self.settings.paper_split_max_attempts + 1):
                retry_instruction = (
                    ""
                    if attempt == 1
                    else "\n\nYour previous response was not valid JSON. Return the complete JSON "
                    "object again, with every key followed by a colon and every string escaped."
                )
                try:
                    payload = split_model.complete(
                        (HarnessMessage(role="user", content=prompt + retry_instruction),),
                        _QuestionSplitPayload,
                        timeout=self.settings.paper_split_timeout,
                    )
                    return [question.model_dump(mode="json") for question in payload.questions]
                except (TypeError, ValueError, json.JSONDecodeError) as error:
                    last_error = error
                    if attempt < self.settings.paper_split_max_attempts:
                        logger.warning(
                            "paper split response rejected; retrying",
                            extra={
                                "event": "paper_split_response_retry",
                                "attempt": attempt,
                                "max_attempts": self.settings.paper_split_max_attempts,
                                "error_type": type(error).__name__,
                            },
                        )
            assert last_error is not None
            raise last_error

        source_documents: list[tuple[str, str, str]] = [
            (
                "primary",
                markdown,
                hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
            )
        ]
        if primary_markdown is not None and markdown.startswith(primary_markdown):
            recovery_markdown = markdown[len(primary_markdown) :].strip()
            source_documents = [
                (
                    "primary",
                    primary_markdown,
                    hashlib.sha256(primary_markdown.encode("utf-8")).hexdigest(),
                )
            ]
            if recovery_markdown:
                source_documents.append(
                    (
                        "recovery",
                        recovery_markdown,
                        hashlib.sha256(recovery_markdown.encode("utf-8")).hexdigest(),
                    )
                )
        batches = [
            (source_kind, source_digest, batch)
            for source_kind, source_markdown, source_digest in source_documents
            for batch in _split_markdown_batches(
                source_markdown,
                max_chars=self.settings.paper_split_max_chars,
                overlap_max_chars=self.settings.paper_split_overlap_max_chars,
            )
        ]
        completed: dict[int, list[dict[str, Any]]] = {}
        pending: list[tuple[int, str, str, str]] = []
        for batch_index, (source_kind, _source_digest, batch) in enumerate(batches):
            digest = hashlib.sha256(
                json.dumps(
                    {
                        "contract": SPLIT_CONTRACT_VERSION,
                        "model": self.settings.paper_split_model,
                        "reasoning_effort": self.settings.paper_split_reasoning_effort,
                        "source_kind": source_kind,
                        "markdown": batch,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            cached = load_checkpoint(batch_index, digest) if load_checkpoint else None
            if cached is None:
                pending.append((batch_index, digest, batch, source_kind))
            else:
                completed[batch_index] = cached

        first_error: Exception | None = None
        if pending:
            with ThreadPoolExecutor(
                max_workers=min(self.settings.paper_split_concurrency, len(pending))
            ) as executor:
                futures = {
                    executor.submit(split_batch, batch, source_kind): (
                        batch_index,
                        digest,
                        time.monotonic(),
                    )
                    for batch_index, digest, batch, source_kind in pending
                }
                for future in as_completed(futures):
                    batch_index, digest, batch_started = futures[future]
                    try:
                        questions = future.result()
                        completed[batch_index] = questions
                        if save_checkpoint:
                            save_checkpoint(
                                batch_index,
                                len(batches),
                                digest,
                                questions,
                                (time.monotonic() - batch_started) * 1000,
                            )
                    except Exception as error:
                        first_error = first_error or error
        if first_error is not None:
            raise first_error

        extracted: list[dict[str, Any]] = []
        for batch_index, (source_kind, source_digest, _batch) in enumerate(batches):
            for item in completed.get(batch_index, []):
                tagged = dict(item)
                tagged["_split_source"] = source_kind
                tagged["_split_source_digest"] = source_digest
                tagged["_split_batch_index"] = batch_index
                extracted.append(tagged)
        return extracted

    @staticmethod
    def _cited_knowledge_codes(
        answer_markdown: str,
        citations: list[Citation],
        catalog_by_code: dict[str, dict[str, Any]],
    ) -> list[str]:
        codes: list[str] = []
        for citation_id in citation_ids_in_markdown(answer_markdown):
            citation_index = int(citation_id.removeprefix("S")) - 1
            if not 0 <= citation_index < len(citations):
                continue
            code = citations[citation_index].knowledge_code
            if code and code in catalog_by_code and code not in codes:
                codes.append(code)
                if len(codes) == 4:
                    break
        return codes

    def _knowledge_references(
        self,
        codes: list[str],
        catalog_by_code: dict[str, dict[str, Any]],
        answer_citations: list[Citation],
    ) -> list[PaperKnowledgeReference]:
        references: list[PaperKnowledgeReference] = []
        for code in codes:
            point = catalog_by_code.get(code)
            if not point:
                continue
            related = [citation for citation in answer_citations if citation.knowledge_code == code]
            source_ref = str(point["source_ref"])
            stored = [
                Citation.model_validate(reference) for reference in point.get("references", [])
            ]
            merged: list[Citation] = []
            seen: set[tuple[Any, ...]] = set()
            for citation in [*stored, *related]:
                key = (
                    citation.document_id,
                    citation.source,
                    citation.page,
                    citation.section,
                    citation.excerpt[:240],
                )
                if key in seen:
                    continue
                seen.add(key)
                merged.append(citation)
            references.append(
                PaperKnowledgeReference(
                    code=point["code"],
                    title=point["title"],
                    node_type=point["features"].get("node_type", "topic"),
                    difficulty_score=point["difficulty_score"],
                    difficulty_label=point["difficulty_label"],
                    difficulty_confidence=point["difficulty_confidence"],
                    evidence_level=point["evidence_level"],
                    source_ref=source_ref,
                    references=merged[:6],
                    definition=point.get("definition", ""),
                    breadcrumb=point.get("breadcrumb", ""),
                    path=point.get("path", []),
                    relations=point.get("relations", []),
                    difficulty=point.get("difficulty"),
                )
            )
        return references

    def _answer_one(
        self,
        item: dict[str, Any],
        catalog: list[dict[str, Any]],
        unit_code: str | None,
        pair_key: str | None = None,
        source_booklet_document_id: str | None = None,
        source_booklet_checksum: str | None = None,
        event_sink: AgentEventSink | None = None,
        ledger: AgentRunLedger | None = None,
    ) -> PaperQuestionAnswer:
        number = str(item.get("number", "?")).strip() or "?"
        question = str(item.get("question_markdown", "")).strip()
        if not question:
            raise ValueError(f"第 {number} 题题干为空")
        raw_images = item.get("question_images", ())
        if not isinstance(raw_images, (list, tuple)) or not all(
            isinstance(image, QuestionImage) for image in raw_images
        ):
            raise ValueError(f"第 {number} 题原题页图不是可信的 QuestionImage")
        question_images = tuple(raw_images)
        question_spec = question_spec_from_item(item)
        catalog_by_code = {point["code"]: point for point in catalog}
        request_parts = [
            (
                "Solve the following examination question completely. Show all necessary "
                "mathematical working. If the requested answer includes a sketch or "
                "construction, include a diagram."
            ),
            question,
        ]
        source_types: list[str] = []
        rag_options: dict[str, Any] = {
            "question_images": question_images,
            "question_number": number,
            "question_spec": question_spec,
            "visual_request_text": question,
            "event_sink": event_sink,
        }
        if ledger is not None:
            rag_options["ledger"] = ledger
        response = self.rag.ask(
            AskRequest(
                question="\n\n".join(request_parts),
                subject_code=self.subject.subject_code,
                unit_code=unit_code,
                pair_key=pair_key,
                source_booklet_document_id=source_booklet_document_id,
                source_booklet_checksum=source_booklet_checksum,
                authority_tiers=[
                    "official",
                    "licensed_core",
                    "licensed",
                    "supplementary",
                ],
                source_types=source_types,
                top_k=6,
            ),
            **rag_options,
        )
        codes = self._cited_knowledge_codes(
            response.answer_markdown,
            response.citations,
            catalog_by_code,
        )
        return PaperQuestionAnswer(
            number=number,
            question_markdown=question,
            answer_markdown=response.answer_markdown,
            diagrams=response.diagrams,
            images=response.images,
            citations=response.citations,
            knowledge_points=self._knowledge_references(
                codes,
                catalog_by_code,
                response.citations,
            ),
            confidence=response.confidence,
            grounded=response.grounded,
            warnings=[
                *response.warnings,
                *(
                    ["试卷身份未完整解析，本题未检索 Mark Scheme，以避免跨卷证据污染。"]
                    if pair_key is None
                    else []
                ),
            ],
        )

    def split_questions(
        self,
        markdown: str,
        *,
        unit_code: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._split_questions(
            markdown,
            unit_code=unit_code,
        )

    def split_questions_checkpointed(
        self,
        markdown: str,
        *,
        unit_code: str | None = None,
        source_markdown: str | None = None,
        load_checkpoint: SplitCheckpointLoader,
        save_checkpoint: SplitCheckpointSaver,
    ) -> list[dict[str, Any]]:
        """Split a paper in bounded batches and reuse only digest-matched results."""

        return self._split_questions(
            markdown,
            unit_code=unit_code,
            source_markdown=source_markdown,
            load_checkpoint=load_checkpoint,
            save_checkpoint=save_checkpoint,
        )

    def _repair_question_structure(
        self,
        source_markdown: str,
        items: list[dict[str, Any]],
        unresolved_numbers: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        excerpt_limit = max(
            800,
            min(
                self.settings.paper_repair_candidate_max_chars,
                self.settings.paper_repair_candidate_budget_chars // len(items),
            ),
        )
        candidates = [
            {
                "candidate_index": index,
                "number": str(item.get("number", "?")),
                "question_excerpt": str(item.get("question_markdown", ""))[:excerpt_limit],
                "answer_requirements": item.get("answer_requirements") or [],
                "source_kind": item.get("_split_source", "primary"),
                "batch_index": item.get("_split_batch_index"),
            }
            for index, item in enumerate(items)
        ]
        source_limit = self.settings.paper_repair_source_max_chars
        if len(source_markdown) > source_limit:
            leading_chars = source_limit // 2
            trailing_chars = source_limit - leading_chars
            source_excerpt = (
                source_markdown[:leading_chars]
                + "\n\n[... trusted source middle omitted ...]\n\n"
                + source_markdown[-trailing_chars:]
            )
        else:
            source_excerpt = source_markdown
        system_prompt = (
            "Repair only the grouping and physical order of extracted examination-question "
            "candidates. Return one group per top-level question in trusted source order. "
            "Group duplicate candidates and subquestion fragments under their top-level "
            "question. Use every candidate_index exactly once. Keep each group's number "
            "within the number family present in that group's candidates. For every group, "
            "set preferred_candidate_index to the candidate whose wording and subpart/mark "
            "structure best match the trusted source. Prefer primary over recovery. The "
            "preferred index must belong to that group's candidate_indexes. Do not solve, "
            "rewrite, discard, or add questions, and do not infer source page numbers."
        )
        request_payload = {
            "unresolved_numbers": unresolved_numbers,
            "trusted_source_excerpt": source_excerpt,
            "candidates": candidates,
        }
        task = StructuredTask(
            system_prompt=system_prompt,
            user_content=json.dumps(request_payload, ensure_ascii=False),
        )
        model = self.structured_model
        if model is None:
            model = _build_question_repair_model(self.settings)
            self.structured_model = model
        runner = StructuredTaskRunner(model)
        plan = runner.run(
            task,
            _QuestionRepairPlan,
            timeout=self.settings.paper_split_timeout,
        )
        try:
            repaired = _apply_question_repair_plan(items, plan)
        except ValueError as first_error:
            indexes = [index for group in plan.groups for index in group.candidate_indexes]
            expected_indexes = list(range(len(items)))
            missing_indexes = sorted(set(expected_indexes) - set(indexes))
            duplicate_indexes = sorted(index for index in set(indexes) if indexes.count(index) > 1)
            invalid_indexes = sorted(set(indexes) - set(expected_indexes))
            correction = StructuredTask(
                system_prompt=system_prompt,
                user_content=json.dumps(
                    {
                        **request_payload,
                        "previous_invalid_plan": plan.model_dump(mode="json"),
                        "deterministic_validation_error": str(first_error),
                        "required_candidate_indexes": expected_indexes,
                        "missing_candidate_indexes": missing_indexes,
                        "duplicate_candidate_indexes": duplicate_indexes,
                        "invalid_candidate_indexes": invalid_indexes,
                        "correction_instruction": (
                            "Return one corrected replacement plan. Fix the deterministic "
                            "validation error without changing, dropping or inventing candidates."
                        ),
                    },
                    ensure_ascii=False,
                ),
            )
            corrected_plan = runner.run(
                correction,
                _QuestionRepairPlan,
                timeout=self.settings.paper_split_timeout,
            )
            repaired = _apply_question_repair_plan(items, corrected_plan)
        for item in repaired:
            spec = question_spec_from_item(item)
            item["answer_requirements"] = [part.model_dump(mode="json") for part in spec.subparts]
            item["total_marks"] = spec.total_marks
        return repaired

    def _split_questions(
        self,
        markdown: str,
        *,
        unit_code: str | None,
        source_markdown: str | None = None,
        load_checkpoint: SplitCheckpointLoader | None = None,
        save_checkpoint: SplitCheckpointSaver | None = None,
    ) -> list[dict[str, Any]]:
        if len(markdown.strip()) < 20:
            raise ValueError("解析后的试卷内容过短，无法识别题目")
        catalog = self._catalog(unit_code)
        trusted_source = source_markdown or markdown
        repair_candidates: list[dict[str, Any]]
        if self.splitter is None:
            extracted = _drop_covered_recovery_fragments(
                _align_primary_question_numbers_from_recovery(
                    self._split_with_llm(
                        markdown,
                        catalog,
                        primary_markdown=source_markdown,
                        load_checkpoint=load_checkpoint,
                        save_checkpoint=save_checkpoint,
                    )
                )
            )
            repair_candidates = extracted
            try:
                questions = _merge_split_questions(extracted)
            except _QuestionCandidateConflict as merge_error:
                try:
                    questions = self._repair_question_structure(
                        trusted_source,
                        extracted,
                        merge_error.question_numbers,
                    )
                except Exception as repair_error:
                    raise ValueError(
                        f"{merge_error}；模型定向修复失败：{repair_error}"
                    ) from repair_error
        else:
            questions = self.splitter(markdown, catalog)
            repair_candidates = questions
        normalized = [item for item in questions if str(item.get("question_markdown", "")).strip()]
        if not normalized:
            raise ValueError("没有识别到顶层题目，请检查试卷内容或 MinerU 解析结果")
        damaged = [
            str(item.get("number", "?"))
            for item in normalized
            if question_has_unresolved_source_placeholder(str(item.get("question_markdown", "")))
        ]
        if damaged:
            raise ValueError("题目包含未修复的原卷占位符：" + ", ".join(damaged))
        for item in normalized:
            spec = question_spec_from_item(item)
            item["answer_requirements"] = [part.model_dump(mode="json") for part in spec.subparts]
            item["total_marks"] = spec.total_marks
        try:
            reconciled = reconcile_question_source_pages(trusted_source, normalized)
        except QuestionSourcePageResolutionError as source_error:
            try:
                repaired = self._repair_question_structure(
                    trusted_source,
                    normalized,
                    source_error.unresolved_numbers,
                )
            except Exception as repair_error:
                raise ValueError(f"{source_error}；结构修复失败：{repair_error}") from repair_error
            reconciled = reconcile_question_source_pages(trusted_source, repaired)
        try:
            validated = validate_question_source_structure(trusted_source, reconciled)
        except QuestionSourceStructureError as source_error:
            number_match = re.search(r"第\s*(\d+)\s*题", str(source_error))
            unresolved_numbers = (
                (number_match.group(1),)
                if number_match
                else tuple(dict.fromkeys(str(item.get("number", "?")) for item in reconciled))
            )
            try:
                repaired = self._repair_question_structure(
                    trusted_source,
                    repair_candidates,
                    unresolved_numbers,
                )
                reconciled = reconcile_question_source_pages(trusted_source, repaired)
                validated = validate_question_source_structure(trusted_source, reconciled)
            except Exception as repair_error:
                raise ValueError(f"{source_error}；结构修复失败：{repair_error}") from repair_error
        damaged = [
            str(item.get("number", "?"))
            for item in validated
            if question_has_unresolved_source_placeholder(str(item.get("question_markdown", "")))
        ]
        if damaged:
            raise ValueError("主源包含未修复的原卷占位符：" + ", ".join(damaged))
        return validated

    def answer_question(
        self,
        item: dict[str, Any],
        *,
        unit_code: str | None = None,
        pair_key: str | None = None,
        source_booklet_document_id: str | None = None,
        source_booklet_checksum: str | None = None,
        event_sink: AgentEventSink | None = None,
        ledger: AgentRunLedger | None = None,
    ) -> PaperQuestionAnswer:
        return self._answer_one(
            item,
            self._catalog(unit_code),
            unit_code,
            pair_key,
            source_booklet_document_id,
            source_booklet_checksum,
            event_sink,
            ledger,
        )

    def answer(
        self,
        filename: str,
        content: bytes,
        *,
        unit_code: str | None = None,
    ) -> PaperAnswerResponse:
        markdown = self.parser(self.settings, filename, content).strip()
        normalized = self.split_questions(markdown, unit_code=unit_code)
        catalog = self._catalog(unit_code)
        pair_key = parse_exam_identity(
            Path(filename),
            "question_paper",
            self.subject.pack,
        )["pair_key"]

        answers: list[PaperQuestionAnswer | None] = [None] * len(normalized)
        worker_count = min(self.settings.paper_question_concurrency, len(normalized))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(self._answer_one, item, catalog, unit_code, pair_key): index
                for index, item in enumerate(normalized)
            }
            for future in as_completed(futures):
                index = futures[future]
                item = normalized[index]
                try:
                    answers[index] = future.result()
                except Exception as error:
                    answers[index] = PaperQuestionAnswer(
                        number=str(item.get("number", "?")),
                        question_markdown=str(item.get("question_markdown", "")),
                        answer_markdown="",
                        confidence=0,
                        grounded=False,
                        warnings=["该题作答失败，可单独重试。"],
                        error=str(error)[:500],
                    )

        completed = [answer for answer in answers if answer is not None]
        failed = sum(1 for answer in completed if answer.error is not None)
        return PaperAnswerResponse(
            filename=filename,
            detected_questions=len(completed),
            succeeded=len(completed) - failed,
            failed=failed,
            questions=completed,
        )
