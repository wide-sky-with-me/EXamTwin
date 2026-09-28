from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from examtwin.assessment.assessment_repository import AssessmentRepository
from examtwin.assessment.grade_boundaries import estimate_unit_grade
from examtwin.assessment.grading import GradingService
from examtwin.assessment.paper_job_repository import PaperJobRepository
from examtwin.assessment.policies import FOUNDATION_SCORE_PERCENTAGE, STABLE_SCORE_PERCENTAGE
from examtwin.assessment.rubric_repository import RubricConflictError, RubricRepository
from examtwin.contracts.grading import GradeRequest, GradeResponse
from examtwin.contracts.papers import PaperQuestionAnswer
from examtwin.contracts.rubrics import (
    AiReviewRubricCriteriaRequest,
    BatchReviewRubricCriteriaRequest,
    RubricCriterionPatch,
)
from examtwin.knowledge.public import CorpusRepository, parse_exam_identity
from examtwin.platform.agent_runtime import (
    StructuredModelPort,
    StructuredTask,
    StructuredTaskRunner,
)
from examtwin.platform.cache_paths import (
    MarkdownCacheMissing,
    MarkdownCacheStore,
    resolve_markdown_cache_path,
)
from examtwin.platform.config import Settings
from examtwin.platform.prompts import load_prompt_template
from examtwin.platform.structured_model import LiteLLMStructuredModel
from examtwin.subjects.public import SubjectContext

_CONTROL_CHARACTER = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _reject_control_characters(value: object) -> object:
    strings = [value] if isinstance(value, str) else value
    if not isinstance(strings, list):
        return value
    if any(isinstance(item, str) and _CONTROL_CHARACTER.search(item) for item in strings):
        raise ValueError("评分原子文本包含控制字符")
    return value


class RubricCriterionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_number: str
    subpart: str = "whole"
    criterion_id: str
    scoring_mode: Literal["point_based", "levels_based"]
    mark_type: str | None = None
    max_marks: float = Field(gt=0)
    description: str
    dependencies: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    accuracy_requirement: str | None = None
    units: list[str] = Field(default_factory=list)
    follow_through_policy: str | None = None
    source_page: int | None = None
    source_excerpt: str
    confidence: float = Field(ge=0, le=1)

    _valid_text = field_validator(
        "question_number",
        "subpart",
        "criterion_id",
        "mark_type",
        "description",
        "dependencies",
        "alternatives",
        "accuracy_requirement",
        "units",
        "follow_through_policy",
        "source_excerpt",
    )(_reject_control_characters)


class RubricExtractionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria: list[RubricCriterionDraft] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class AiReviewModelError(RuntimeError):
    """The model failed to return one valid review for every requested criterion."""


class AiRubricCriterionReviewDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str
    recommendation: Literal["accept", "reject", "revise"]
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1)
    suggested_updates: RubricCriterionPatch | None = None

    @field_validator("suggested_updates", mode="before")
    @classmethod
    def omit_null_update_placeholders(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        updates = {key: item for key, item in value.items() if item is not None}
        return updates or None


class AiRubricQuestionReviewDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviews: list[AiRubricCriterionReviewDraft] = Field(min_length=1, max_length=200)


def _rubric_review_system_prompt() -> str:
    return load_prompt_template("grading/rubric_review_v1.md")


_NON_SCORING_CRITERION_FIELDS = frozenset(
    {
        "id",
        "criterion_fingerprint",
        "review_status",
        "reviewed_by",
        "reviewed_at",
        "ai_review",
    }
)


def _criterion_scoring_payload(
    criterion: Mapping[str, object],
) -> dict[str, object]:
    return {
        key: value for key, value in criterion.items() if key not in _NON_SCORING_CRITERION_FIELDS
    }


def _actionable_review_updates(
    criterion: Mapping[str, object],
    updates: RubricCriterionPatch | None,
) -> dict[str, object] | None:
    if updates is None:
        return None
    proposed = updates.model_dump(exclude_unset=True)
    actionable = {key: value for key, value in proposed.items() if criterion.get(key) != value}
    return actionable or None


def _review_question_criteria(
    model: StructuredModelPort,
    settings: Settings,
    question: Mapping[str, object],
    mark_scheme: str,
    criteria: list[dict[str, object]],
) -> list[dict[str, object]]:
    expected_ids = [str(item["id"]) for item in criteria]
    fingerprints = {str(item["id"]): str(item["criterion_fingerprint"]) for item in criteria}
    number = str(question["number"])
    prompt_criteria = [
        {
            **{
                key: value
                for key, value in _criterion_scoring_payload(item).items()
                if key != "criterion_id"
            },
            "review_id": str(item["id"]),
            "criterion_label": str(item["criterion_id"]),
        }
        for item in criteria
    ]
    user_content = (
        f"TARGET QUESTION: {number}\n\n"
        f"QUESTION {number}:\n"
        f"{str(question['question_markdown'])[: settings.rubric_question_max_chars]}\n\n"
        "OFFICIAL MARK SCHEME EXCERPT:\n"
        f"{_mark_scheme_context(mark_scheme, number, settings=settings)}\n\n"
        "CURRENT RUBRIC CRITERIA:\n"
        f"{json.dumps(prompt_criteria, ensure_ascii=False, indent=2, default=str)}"
    )
    try:
        runner = StructuredTaskRunner(model)
        payload = runner.run(
            StructuredTask(
                system_prompt=_rubric_review_system_prompt(),
                user_content=user_content,
            ),
            AiRubricQuestionReviewDraft,
            timeout=settings.grading_timeout,
        )
        output_ids = [item.review_id for item in payload.reviews]
        id_mismatch = Counter(output_ids) != Counter(expected_ids)
        criteria_by_id = {str(item["id"]): item for item in criteria}
        empty_revise_ids = [
            item.review_id
            for item in payload.reviews
            if item.recommendation == "revise"
            and (
                item.review_id not in criteria_by_id
                or _actionable_review_updates(
                    criteria_by_id[item.review_id],
                    item.suggested_updates,
                )
                is None
            )
        ]
        if id_mismatch or empty_revise_ids:
            correction_reasons: list[str] = []
            if id_mismatch:
                correction_reasons.append(
                    "Return exactly one entry for every expected review_id. "
                    f"Expected: {expected_ids}. Previous response: {output_ids}."
                )
            if empty_revise_ids:
                correction_reasons.append(
                    "The previous response selected revise without a concrete non-null "
                    "suggested update for review_id(s): "
                    f"{', '.join(empty_revise_ids)}. For each listed ID, either include at "
                    "least one concrete field change or choose accept/reject instead."
                )
            payload = runner.run(
                StructuredTask(
                    system_prompt=_rubric_review_system_prompt(),
                    user_content=(
                        f"{user_content}\n\nCORRECTION REQUIRED:\n"
                        + "\n".join(correction_reasons)
                        + "\nReturn the complete review list again."
                    ),
                ),
                AiRubricQuestionReviewDraft,
                timeout=settings.grading_timeout,
            )
        output_ids = [item.review_id for item in payload.reviews]
        if Counter(output_ids) != Counter(expected_ids):
            raise AiReviewModelError(
                f"AI 审核结果 ID 不闭合（期望 {expected_ids}，实际 {output_ids}）"
            )
        reviews: list[dict[str, object]] = []
        for item in payload.reviews:
            updates = _actionable_review_updates(
                criteria_by_id[item.review_id],
                item.suggested_updates,
            )
            if item.recommendation == "revise" and not updates:
                raise AiReviewModelError("AI 的 revise 建议必须包含有效修改")
            rationale = item.rationale.strip()
            if not rationale:
                raise AiReviewModelError("AI 审核理由不能为空")
            reviews.append(
                {
                    "criterion_id": item.review_id,
                    "recommendation": item.recommendation,
                    "confidence": item.confidence,
                    "rationale": rationale,
                    "suggested_updates": updates,
                    "criterion_fingerprint": fingerprints[item.review_id],
                }
            )
        return reviews
    except AiReviewModelError:
        raise
    except Exception as error:
        raise AiReviewModelError("AI 评分原子审核失败") from error


_ERROR_TYPE_ORDER = (
    "conceptual",
    "procedural",
    "calculation",
    "notation",
    "unit",
    "diagram",
    "omission",
)


def _assessment_diagnostics(result: object) -> tuple[list[str], list[str]]:
    if not isinstance(result, Mapping):
        return [], []
    error_types: list[str] = []
    suggestions: list[str] = []
    seen_errors: set[str] = set()
    seen_suggestions: set[str] = set()

    top_level_suggestions = result.get("improvement_suggestions", [])
    if isinstance(top_level_suggestions, list):
        for value in top_level_suggestions:
            suggestion = str(value).strip()
            if suggestion and suggestion not in seen_suggestions:
                seen_suggestions.add(suggestion)
                suggestions.append(suggestion)

    awards = result.get("rubric_awards", [])
    if not isinstance(awards, list):
        return error_types, suggestions
    for award in awards:
        if not isinstance(award, Mapping):
            continue
        values = award.get("error_types", [])
        if isinstance(values, list):
            for value in values:
                error_type = str(value)
                if error_type and error_type not in seen_errors:
                    seen_errors.add(error_type)
                    error_types.append(error_type)
        suggestion_value = award.get("improvement_suggestion")
        if suggestion_value is not None:
            suggestion = str(suggestion_value).strip()
            if suggestion and suggestion not in seen_suggestions:
                seen_suggestions.add(suggestion)
                suggestions.append(suggestion)
    return error_types, suggestions


def _overall_suggestion(
    *,
    completed_questions: int,
    total_questions: int,
    percentage: float | None,
    common_error_types: list[str],
    suggestions: list[str],
) -> str:
    if completed_questions < total_questions:
        lead = f"当前已完成 {completed_questions}/{total_questions} 题评分，请先完成未评分题目。"
    elif percentage is None:
        lead = "当前评分规则没有可汇总的分值。"
    elif percentage >= STABLE_SCORE_PERCENTAGE:
        lead = "整体得分较稳定，请继续巩固作答的完整性与准确性。"
    elif percentage >= FOUNDATION_SCORE_PERCENTAGE:
        lead = "整体基础已建立，仍需针对失分环节逐项改进。"
    else:
        lead = "当前得分显示关键知识与解题步骤仍需系统巩固。"
    details: list[str] = [lead]
    if common_error_types:
        details.append("优先关注：" + "、".join(common_error_types[:3]) + "。")
    if suggestions:
        details.append("建议：" + "；".join(suggestions[:3]) + "。")
    return "".join(details)


_QUESTION_LABEL = re.compile(
    r"^\s*(?:question|q)?\s*[:#]?\s*0*(?P<number>\d+)"
    r"(?P<subpart>(?:(?:\s*\([a-z0-9]+\))|(?:\s*[._/-]\s*[a-z0-9]+))*)\s*$",
    re.IGNORECASE,
)
_MARK_SCHEME_TABLE = re.compile(r"<table\b[^>]*>.*?</table>", re.IGNORECASE | re.DOTALL)
_TABLE_FIRST_CELL = re.compile(
    r"<tr\b[^>]*>\s*<td\b[^>]*>(?P<label>.*?)</td>",
    re.IGNORECASE | re.DOTALL,
)
_TABLE_LABEL_STEM = re.compile(
    r"^\s*(?:question|q)?\s*[:#]?\s*0*(?P<number>\d+)(?!\d)",
    re.IGNORECASE,
)
_HTML_TAG = re.compile(r"<[^>]+>")
_TABLE_ROW = re.compile(r"<tr\b[^>]*>(?P<cells>.*?)</tr>", re.IGNORECASE | re.DOTALL)
_TABLE_CELL = re.compile(
    r"<t[dh]\b[^>]*>(?P<value>.*?)</t[dh]>",
    re.IGNORECASE | re.DOTALL,
)
_MARK_SCHEME_ROW_LABEL = re.compile(
    r"^\s*(?:question|q)?\s*0*(?P<number>\d+)"
    r"(?P<subpart>(?:(?:\s*\([a-z0-9]+\))|(?:\s*[._/-]\s*[a-z0-9]+))*)"
    r"\s*(?:alt(?:ernative)?)?\s*$",
    re.IGNORECASE,
)
_MARK_CODE = re.compile(r"(?P<kind>[MmABE])(?P<marks>\d+)(?:(?i:ft))?")
_MARK_CODE_SEQUENCE = re.compile(r"(?:(?:[MmABE])\d+(?:(?i:ft))?)+")
_MARK_TYPE = re.compile(r"^(?P<kind>[MmABE])(?P<marks>\d+)?(?P<follow_through>(?i:ft))?$")
_QUESTION_PREFIX = re.compile(
    r"^\s*(?:question|q)?\s*0*(?P<number>\d+)"
    r"(?=\s*(?:\(|[._/-]))",
    re.IGNORECASE,
)


def _canonical_subpart(question_number: str, subpart: object) -> str:
    value = str(subpart or "whole").strip()
    if not value or value.casefold() == "whole":
        return "whole"
    target = _question_label(question_number)
    prefix = _QUESTION_PREFIX.match(value)
    if target is not None and prefix is not None:
        if str(int(prefix.group("number"))) == target[0]:
            value = value[prefix.end() :].strip()
            value = re.sub(r"^[._/-]\s*", "", value)
    return value or "whole"


def _numeric_marks(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("评分原子分值必须是数字")
    return float(value)


def _canonical_mark_type(mark_type: object, max_marks: object) -> str | None:
    if mark_type is None:
        return None
    value = str(mark_type).strip()
    match = _MARK_TYPE.fullmatch(value)
    if match is None or match.group("marks") is not None:
        return value
    numeric_marks = _numeric_marks(max_marks)
    if not numeric_marks.is_integer():
        return value
    follow_through = "ft" if match.group("follow_through") else ""
    return f"{match.group('kind')}{int(numeric_marks)}{follow_through}"


def _plain_table_cell(value: str) -> str:
    return unescape(_HTML_TAG.sub("", value)).strip()


def _source_subpart(value: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", value.casefold())
    return "".join(f"({token})" for token in tokens) or "whole"


def _mark_scheme_mark_budgets(mark_scheme: str) -> dict[tuple[str, str], float]:
    budgets: dict[tuple[str, str], float] = {}

    def record(key: tuple[str, str] | None, marks: float) -> None:
        if key is not None and marks > 0:
            budgets[key] = max(budgets.get(key, 0), marks)

    for table in _MARK_SCHEME_TABLE.finditer(mark_scheme):
        active_key: tuple[str, str] | None = None
        active_marks = 0.0
        for row in _TABLE_ROW.finditer(table.group(0)):
            cells = [
                _plain_table_cell(cell.group("value"))
                for cell in _TABLE_CELL.finditer(row.group("cells"))
            ]
            if not cells:
                continue
            label = _MARK_SCHEME_ROW_LABEL.fullmatch(cells[0])
            if label is not None:
                record(active_key, active_marks)
                active_key = (
                    str(int(label.group("number"))),
                    _source_subpart(label.group("subpart")),
                )
                active_marks = 0.0
                if len(cells) >= 3:
                    active_marks += sum(
                        int(mark.group("marks")) for mark in _MARK_CODE.finditer(cells[2])
                    )
                continue
            if active_key is None:
                continue
            for cell in cells:
                compact = re.sub(r"\s+", "", cell)
                if _MARK_CODE_SEQUENCE.fullmatch(compact):
                    active_marks += sum(
                        int(mark.group("marks")) for mark in _MARK_CODE.finditer(compact)
                    )
        record(active_key, active_marks)
    return budgets


def _normalized_criterion_text(value: object) -> str:
    return re.sub(r"\W+", " ", str(value or "").casefold()).strip()


def _warning_key(warning: str) -> str:
    normalized = _normalized_criterion_text(warning.replace("_", " "))
    missing_page_phrases = (
        "does not provide",
        "does not include",
        "does not specify",
        "not specified",
        "not identify",
        "is null",
    )
    if "page" in normalized and any(phrase in normalized for phrase in missing_page_phrases):
        return "source-page-unavailable"
    return normalized


def _dedupe_warnings(warnings: list[str]) -> list[str]:
    keys: list[str] = []
    best_by_key: dict[str, str] = {}
    for warning in warnings:
        key = _warning_key(warning)
        if key not in best_by_key:
            keys.append(key)
            best_by_key[key] = warning
            continue
        if len(warning) > len(best_by_key[key]):
            best_by_key[key] = warning
    return [best_by_key[key] for key in keys]


def _validate_rubric_criteria(
    criteria: list[dict[str, object]],
    mark_scheme: str,
    *,
    question_numbers: set[str] | None = None,
) -> None:
    ids = [str(item["criterion_id"]) for item in criteria]
    duplicate_ids = sorted(item for item, count in Counter(ids).items() if count > 1)
    semantic_keys: dict[tuple[object, ...], list[str]] = {}
    for item in criteria:
        key = (
            str(item["question_number"]),
            str(item["subpart"]),
            _numeric_marks(item["max_marks"]),
            _normalized_criterion_text(item["description"]),
            _normalized_criterion_text(item["source_excerpt"]),
        )
        semantic_keys.setdefault(key, []).append(str(item["criterion_id"]))
    duplicate_atoms = [atom_ids for atom_ids in semantic_keys.values() if len(atom_ids) > 1]
    if duplicate_ids or duplicate_atoms:
        labels = duplicate_ids + ["/".join(atom_ids) for atom_ids in duplicate_atoms]
        raise ValueError("评分方案包含重复评分原子：" + "、".join(labels))

    expected = _mark_scheme_mark_budgets(mark_scheme)
    if not expected:
        return
    actual: dict[tuple[str, str], float] = {}
    for item in criteria:
        label = _question_label(str(item["question_number"]))
        if label is None:
            continue
        key = (label[0], _source_subpart(str(item["subpart"])))
        actual[key] = actual.get(key, 0) + _numeric_marks(item["max_marks"])
    mismatches: list[str] = []
    target_stems = {
        label[0]
        for number in (question_numbers or set())
        if (label := _question_label(number)) is not None
    }
    for key, expected_marks in sorted(expected.items()):
        if target_stems and key[0] not in target_stems:
            continue
        actual_marks = actual.get(key, 0)
        if abs(actual_marks - expected_marks) <= 1e-9:
            continue
        number, subpart = key
        mismatches.append(f"Q{number} {subpart}: 原文 {expected_marks:g}，解析 {actual_marks:g}")
    if mismatches:
        raise ValueError("评分原子与 Mark Scheme 分值不一致：" + "；".join(mismatches))


_RUBRIC_SYSTEM_PROMPT = (
    "You extract an auditable typed rubric from an official examination mark scheme. "
    "The caller supplies exactly one target question. Return only criteria for that question, "
    "with question_number exactly equal to its QUESTION label. Return one criterion per "
    "indivisible mark atom. Preserve exact M1/A1/B1/FT labels, explicit dependencies, "
    "accuracy, units, levels descriptors, and LaTeX backslashes. Alternative methods are "
    "mutually exclusive routes to the same mark budget: align equivalent ordinal mark slots "
    "in each criterion's alternatives and never create additive marks for an ALT route. If "
    "aligned routes use different mark labels, preserve both in a slash-separated mark_type. "
    "Use point_based for atomic marks and levels_based only for holistic level bands. Never "
    "invent a mark, infer from a model answer, include question totals as criteria, repeat an "
    "atom, or merge separate atoms."
)

_GENERATED_RUBRIC_SYSTEM_PROMPT = (
    "You are a senior teacher drafting a provisional mark scheme because no official mark "
    "scheme is available. Return an auditable typed rubric for exactly the supplied question. "
    "Use one criterion per indivisible mark. Base every criterion only on the question, its "
    "stated mark budget, and the supplied course context. Preserve valid alternative methods, "
    "accuracy, units, dependencies, and follow-through rules. The sum of max_marks must equal "
    "the question mark budget when one is supplied. Set source_page to null and source_excerpt "
    "to a short statement that this criterion was AI-generated from the question. Never claim "
    "that a criterion came from an official source."
)


def _unique_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        cleaned = value.strip()
        key = _normalized_criterion_text(cleaned)
        if not cleaned or not key or key in seen:
            continue
        seen.add(key)
        unique.append(cleaned)
    return unique


def _collapse_holistic_best_fit_criteria(
    payload: RubricExtractionDraft,
    mark_scheme: str,
    *,
    question: Mapping[str, object],
    settings: Settings,
) -> RubricExtractionDraft:
    """Represent each official best-fit level grid as one non-additive criterion.

    Economics level descriptors and AO weightings are interdependent alternatives for
    choosing one holistic mark.  They are not additive one-mark atoms.  Models often
    expand every descriptor bullet and AO allocation, producing impossible totals and
    dozens of unsaveable review rows.  Collapse only when the official excerpt itself
    declares both interdependence and best-fit marking, and only to budgets parsed from
    that same official source.
    """

    question_number = str(question["number"])
    context = _mark_scheme_context(mark_scheme, question_number, settings=settings)
    normalized_context = _normalized_criterion_text(context)
    if not (
        "interdependent" in normalized_context
        and "best fit" in normalized_context
        and "level" in normalized_context
    ):
        return payload

    label = _question_label(question_number)
    if label is None:
        return payload
    expected = {
        subpart: marks
        for (number, subpart), marks in _mark_scheme_mark_budgets(mark_scheme).items()
        if number == label[0]
    }
    if not expected:
        requirements = question.get("requirements_json")
        if isinstance(requirements, str):
            try:
                requirements = json.loads(requirements or "{}")
            except json.JSONDecodeError:
                requirements = None
        subparts = requirements.get("subparts") if isinstance(requirements, Mapping) else None
        if isinstance(subparts, list):
            expected = {
                _source_subpart(str(item.get("label") or "whole")): float(item["marks"])
                for item in subparts
                if isinstance(item, Mapping)
                and isinstance(item.get("marks"), (int, float))
                and not isinstance(item.get("marks"), bool)
                and float(item["marks"]) > 0
            }
    if not expected:
        budget = _question_mark_budget(question)
        if budget is not None:
            expected = {"whole": budget}
    if not expected:
        return payload

    mapped = _map_criteria_to_questions(payload, {question_number})
    grouped: dict[str, list[dict[str, object]]] = {}
    for item in mapped:
        item_subpart = str(item["subpart"])
        grouped.setdefault(
            "whole" if item_subpart == "whole" else _source_subpart(item_subpart),
            [],
        ).append(item)
    if set(grouped) != set(expected):
        return payload

    collapsed: list[RubricCriterionDraft] = []
    for subpart, budget in sorted(expected.items()):
        items = grouped[subpart]
        descriptions = _unique_text([str(item["description"]) for item in items])
        excerpts = _unique_text([str(item["source_excerpt"]) for item in items])
        alternative_values: list[str] = []
        source_pages: list[int] = []
        confidences: list[float] = []
        for item in items:
            raw_alternatives = item.get("alternatives")
            if isinstance(raw_alternatives, list):
                alternative_values.extend(str(value) for value in raw_alternatives)
            raw_source_page = item.get("source_page")
            if isinstance(raw_source_page, int) and not isinstance(raw_source_page, bool):
                source_pages.append(raw_source_page)
            raw_confidence = item.get("confidence")
            if isinstance(raw_confidence, (int, float)) and not isinstance(raw_confidence, bool):
                confidences.append(float(raw_confidence))
        if len(confidences) != len(items):
            return payload
        alternatives = _unique_text(alternative_values)
        public_subpart = str(items[0]["subpart"])
        collapsed.append(
            RubricCriterionDraft(
                question_number=question_number,
                subpart=public_subpart,
                criterion_id=(
                    f"{question_number}-levels"
                    if public_subpart == "whole"
                    else f"{question_number}{public_subpart}-levels"
                ),
                scoring_mode="levels_based",
                mark_type="LEVELS",
                max_marks=budget,
                description="\n\n".join(descriptions),
                alternatives=alternatives,
                source_page=min(source_pages) if source_pages else None,
                source_excerpt="\n\n".join(excerpts),
                confidence=min(confidences),
            )
        )
    return payload.model_copy(
        update={
            "criteria": collapsed,
            "warnings": [
                *payload.warnings,
                "Official interdependent best-fit level descriptors were preserved as one "
                "non-additive criterion per printed subpart.",
            ],
        }
    )


def _generate_question_rubric(
    model: StructuredModelPort,
    settings: Settings,
    question: Mapping[str, object],
    course_context: str,
) -> RubricExtractionDraft:
    number = str(question["number"])
    requirements = str(question.get("requirements_json") or "{}")
    user_content = (
        f"COURSE CONTEXT:\n{course_context[: settings.rubric_course_context_max_chars]}\n\n"
        f"TARGET QUESTION: {number}\n\n"
        f"QUESTION {number}:\n"
        f"{str(question['question_markdown'])[: settings.rubric_question_max_chars]}\n\n"
        "MARK AND ANSWER REQUIREMENTS:\n"
        f"{requirements[: settings.rubric_requirements_max_chars]}"
    )
    return StructuredTaskRunner(model).run(
        StructuredTask(
            system_prompt=_GENERATED_RUBRIC_SYSTEM_PROMPT,
            user_content=user_content,
        ),
        RubricExtractionDraft,
        timeout=settings.grading_timeout,
    )


def _question_label(value: str) -> tuple[str, str | None] | None:
    match = _QUESTION_LABEL.fullmatch(value)
    if match is None:
        return None
    subpart_tokens = re.findall(r"[a-z0-9]+", match.group("subpart").casefold())
    subpart = (
        subpart_tokens[0]
        if len(subpart_tokens) == 1
        else "".join(f"({token})" for token in subpart_tokens)
    )
    return str(int(match.group("number"))), subpart or None


def _table_question_stems(table: str) -> set[str]:
    first_row = _TABLE_ROW.search(table)
    if first_row is not None:
        headers = {
            _normalized_criterion_text(_plain_table_cell(cell.group("value")))
            for cell in _TABLE_CELL.finditer(first_row.group("cells"))
        }
        if "level" in headers and "marks" in headers:
            return set()
    stems: set[str] = set()
    for match in _TABLE_FIRST_CELL.finditer(table):
        label = unescape(_HTML_TAG.sub("", match.group("label"))).strip()
        prefix = _TABLE_LABEL_STEM.match(label)
        if prefix is not None:
            stems.add(str(int(prefix.group("number"))))
    return stems


def _mark_scheme_context(
    mark_scheme: str,
    question_number: str,
    *,
    settings: Settings,
) -> str:
    max_chars = settings.rubric_mark_scheme_max_chars
    preamble_max_chars = settings.rubric_preamble_max_chars
    following_max_chars = settings.rubric_following_context_max_chars
    tables = list(_MARK_SCHEME_TABLE.finditer(mark_scheme))
    label = _question_label(question_number)
    if not tables or label is None:
        return mark_scheme[:max_chars]
    selected = [
        match.group(0) for match in tables if label[0] in _table_question_stems(match.group(0))
    ]
    if not selected:
        return mark_scheme[:max_chars]
    preamble = mark_scheme[: tables[0].start()][-preamble_max_chars:]
    expanded: list[str] = []
    for selected_table in selected:
        start = mark_scheme.find(selected_table)
        if start < 0:
            expanded.append(selected_table)
            continue
        end = start + len(selected_table)
        next_question = next(
            (
                table.start()
                for table in tables
                if table.start() >= end
                and _table_question_stems(table.group(0))
                and label[0] not in _table_question_stems(table.group(0))
            ),
            min(len(mark_scheme), end + following_max_chars),
        )
        expanded.append(mark_scheme[start:next_question])
    return (f"{preamble}\n\n" + "\n\n".join(expanded))[:max_chars]


def _extract_question_rubric(
    model: StructuredModelPort,
    settings: Settings,
    question: Mapping[str, object],
    mark_scheme: str,
    *,
    correction: str | None = None,
) -> RubricExtractionDraft:
    number = str(question["number"])
    mark_budget = _question_mark_budget(question)
    user_content = (
        f"TARGET QUESTION: {number}\n\n"
        f"QUESTION {number}:\n"
        f"{str(question['question_markdown'])[: settings.rubric_target_question_max_chars]}\n\n"
        "MARK BUDGET FOR TARGET QUESTION:\n"
        f"{mark_budget if mark_budget is not None else 'Not explicitly available.'}\n\n"
        "OFFICIAL MARK SCHEME EXCERPT:\n"
        f"{_mark_scheme_context(mark_scheme, number, settings=settings)}"
    )
    if correction:
        user_content += f"\n\nCORRECTION REQUIRED:\n{correction}"
    runner = StructuredTaskRunner(model)
    schema_correction = (
        "CORRECTION REQUIRED:\nThe previous response failed the rubric schema. Return every "
        "field in the required type and do not emit ASCII control characters. In free-text "
        "fields use ordinary Unicode mathematical notation instead of LaTeX commands that "
        "can be misread as JSON control escapes."
    )
    for attempt in range(3):
        try:
            return runner.run(
                StructuredTask(
                    system_prompt=_RUBRIC_SYSTEM_PROMPT,
                    user_content=user_content,
                ),
                RubricExtractionDraft,
                timeout=settings.grading_timeout,
            )
        except ValidationError:
            if attempt == 2:
                raise
            user_content += f"\n\n{schema_correction}"
    raise AssertionError("unreachable rubric extraction state")


def _map_criteria_to_questions(
    payload: RubricExtractionDraft,
    valid_numbers: set[str],
) -> list[dict[str, object]]:
    candidates: dict[str, list[str]] = {}
    for number in valid_numbers:
        label = _question_label(number)
        if label is not None:
            candidates.setdefault(label[0], []).append(number)
    canonical_numbers = {
        stem: numbers[0] for stem, numbers in candidates.items() if len(numbers) == 1
    }

    criteria: list[dict[str, object]] = []
    for item in payload.criteria:
        values = item.model_dump()
        mapped_number: str | None = None
        label = _question_label(item.question_number)
        if item.question_number in valid_numbers:
            mapped_number = item.question_number
        elif label is not None:
            mapped_number = canonical_numbers.get(label[0])
        if mapped_number is None:
            continue
        values["question_number"] = mapped_number
        if values["subpart"] == "whole" and label is not None and label[1] is not None:
            values["subpart"] = label[1]
        values["subpart"] = _canonical_subpart(mapped_number, values["subpart"])
        values["mark_type"] = _canonical_mark_type(
            values["mark_type"],
            values["max_marks"],
        )
        criteria.append(values)
    return criteria


def _question_mark_budget(question: Mapping[str, object]) -> float | None:
    value = question.get("total_marks")
    if value is None:
        requirements = question.get("requirements_json")
        if isinstance(requirements, str):
            try:
                requirements = json.loads(requirements or "{}")
            except json.JSONDecodeError:
                requirements = None
        if isinstance(requirements, Mapping):
            value = requirements.get("total_marks")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    budget = float(value)
    return budget if budget > 0 else None


def _extract_validated_question_rubric(
    model: StructuredModelPort,
    settings: Settings,
    question: Mapping[str, object],
    mark_scheme: str,
) -> RubricExtractionDraft:
    number = str(question["number"])
    budget = _question_mark_budget(question)
    payload = _extract_question_rubric(model, settings, question, mark_scheme)
    last_error = ""
    for attempt in range(3):
        payload = _collapse_holistic_best_fit_criteria(
            payload,
            mark_scheme,
            question=question,
            settings=settings,
        )
        mapped = _map_criteria_to_questions(payload, {number})
        violations: list[str] = []
        actual = sum(_numeric_marks(item["max_marks"]) for item in mapped)
        if not mapped:
            violations.append("No scoring atoms mapped to the target question.")
        if budget is not None and abs(actual - budget) > 1e-9:
            violations.append(
                f"The extracted atoms total {actual:g} marks, but the Question Paper "
                f"requires exactly {budget:g}."
            )
        try:
            _validate_rubric_criteria(
                mapped,
                mark_scheme,
                question_numbers={number},
            )
        except ValueError as error:
            violations.append(str(error))
        if not violations:
            return payload
        last_error = " ".join(dict.fromkeys(violations))
        if attempt == 2:
            break
        payload = _extract_question_rubric(
            model,
            settings,
            question,
            mark_scheme,
            correction=(
                f"The previous extraction failed deterministic validation: {last_error} "
                "Re-read the official rows for this target question and return a complete, "
                "non-duplicated set of scoring atoms. Match every official subpart budget "
                "and the whole-question budget exactly. Do not score totals, checks, notes, "
                "or alternative routes as extra marks."
            ),
        )
    raise ValueError(f"Q{number} 评分原子校验失败：{last_error}")


def _structured_model(settings: Settings) -> StructuredModelPort:
    credential = settings.llm_api_key
    if credential is None or not credential.get_secret_value():
        raise RuntimeError("LLM credential is required for mark-scheme parsing")
    return LiteLLMStructuredModel(
        model=settings.grading_model,
        provider=settings.litellm_provider,
        api_base=settings.llm_base_url,
        api_key=credential.get_secret_value(),
        reasoning_effort=settings.grading_reasoning_effort,
        max_retries=1,
    )


class RubricService:
    """Parse reusable rubrics and assess persisted paper-answer records."""

    def __init__(
        self,
        settings: Settings,
        subject: SubjectContext,
        documents: CorpusRepository,
        papers: PaperJobRepository,
        rubrics: RubricRepository,
        assessments: AssessmentRepository,
        grading: GradingService,
        *,
        structured_model: StructuredModelPort | None = None,
        markdown_cache: MarkdownCacheStore | None = None,
    ) -> None:
        self.settings = settings
        self.subject = subject
        self.documents = documents
        self.papers = papers
        self.rubrics = rubrics
        self.assessments = assessments
        self.grading = grading
        self.structured_model = structured_model
        self.markdown_cache = markdown_cache or MarkdownCacheStore(settings.markdown_dir)

    def _document_markdown(
        self,
        document: dict[str, object],
        *,
        expected_checksum: str,
    ) -> str:
        self._require_converted_source(document, expected_checksum)
        markdown_path = document.get("markdown_path")
        if not markdown_path:
            raise ValueError("评分方案尚未完成 Markdown 转换")
        try:
            path = resolve_markdown_cache_path(
                self.settings,
                str(document["id"]),
                str(markdown_path),
            )
            return Path(path).read_text(encoding="utf-8")
        except (OSError, MarkdownCacheMissing) as error:
            raise ValueError("评分方案 Markdown 缓存不可用，请先重新转换") from error

    @staticmethod
    def _require_converted_source(
        document: Mapping[str, object],
        expected_checksum: str,
    ) -> None:
        if str(document.get("converted_source_checksum") or "") != expected_checksum:
            raise ValueError("Mark Scheme Markdown 与当前来源版本不一致，请先重新转换")

    def _require_matching_rubric_source(
        self,
        rubric: Mapping[str, object],
        document: dict[str, object] | None,
    ) -> dict[str, object]:
        identity = rubric.get("identity")
        expected_pair = str(identity.get("pair_key") or "") if isinstance(identity, Mapping) else ""
        source_kind = (
            str(identity.get("source_kind") or "official")
            if isinstance(identity, Mapping)
            else "official"
        )
        expected_document_id = str(rubric.get("source_document_id") or "")
        expected_checksum = str(rubric.get("source_document_checksum") or "")
        if document is None:
            raise RubricConflictError("评分规则来源 Mark Scheme 已发生变化，请重新创建评分规则")
        current_pair = str(document.get("pair_key") or "")
        invalid = (
            str(document.get("id") or "") != expected_document_id
            or document.get("subject_code") != self.subject.subject_code
            or document.get("source_type") != "mark_scheme"
            or str(document.get("checksum") or "") != expected_checksum
            or document.get("identity_status") != "complete"
            or not expected_pair
            or current_pair != expected_pair
        )
        if source_kind != "ai_generated":
            parsed_identity = parse_exam_identity(
                Path(str(document.get("filename") or "")),
                "mark_scheme",
                self.subject.pack,
            )
            invalid = invalid or str(parsed_identity.get("pair_key") or "") != expected_pair
        if invalid:
            raise RubricConflictError("评分规则来源 Mark Scheme 已发生变化，请重新创建评分规则")
        self._require_converted_source(document, expected_checksum)
        return document

    def create(self, *, paper_job_id: str, source_document_id: str) -> dict[str, object]:
        job = self.papers.get(paper_job_id)
        if job is None or job["subject_code"] != self.subject.subject_code:
            raise LookupError("试卷作答任务不存在")
        if job["status"] not in {"completed", "partial_failed"}:
            raise ValueError("只能为已完成作答的试卷创建评分规则")
        document = self.documents.get(source_document_id)
        if (
            document is None
            or document.get("status") == "deleted"
            or document.get("subject_code") != self.subject.subject_code
        ):
            raise LookupError("评分方案文档不存在")
        if document.get("source_type") != "mark_scheme":
            raise ValueError("所选文档不是 Mark Scheme")
        document_checksum = str(document.get("checksum") or "")
        if not document_checksum:
            raise ValueError("Mark Scheme 缺少校验和，无法冻结评分规则来源版本")
        self._require_converted_source(document, document_checksum)
        job_pair = str(job.get("pair_key") or "")
        if not job_pair:
            job_identity = parse_exam_identity(
                Path(str(job.get("filename") or "")),
                "question_paper",
                self.subject.pack,
            )
            job_pair = str(job_identity.get("pair_key") or "")
        document_pair = str(document.get("pair_key") or "")
        if not job_pair:
            raise ValueError("Question Paper 缺少完整考试身份，无法验证评分方案配对")
        if document.get("identity_status") != "complete" or not document_pair:
            raise ValueError("Mark Scheme 缺少完整考试身份，无法验证评分方案配对")
        if job_pair != document_pair:
            raise ValueError("Mark Scheme 与试卷的年份、考季或 Unit 不匹配")

        questions = self.papers.questions(paper_job_id)
        if not questions:
            raise ValueError("试卷任务没有可评分题目")
        mark_scheme = self._document_markdown(
            document,
            expected_checksum=document_checksum,
        )
        model = self.structured_model or _structured_model(self.settings)
        with ThreadPoolExecutor(max_workers=min(4, len(questions))) as executor:
            payloads = list(
                executor.map(
                    lambda question: _extract_validated_question_rubric(
                        model,
                        self.settings,
                        question,
                        mark_scheme,
                    ),
                    questions,
                )
            )

        valid_numbers = {str(row["number"]) for row in questions}
        criteria: list[dict[str, object]] = []
        warnings: list[str] = []
        for question, payload in zip(questions, payloads, strict=True):
            number = str(question["number"])
            criteria.extend(_map_criteria_to_questions(payload, {number}))
            warnings.extend(payload.warnings)
        if not criteria:
            raise ValueError("评分方案未能映射到试卷题号")
        _validate_rubric_criteria(criteria, mark_scheme)
        omitted = sorted(valid_numbers - {str(item["question_number"]) for item in criteria})
        if omitted:
            warnings.append("未抽取到评分原子的题目：" + "、".join(omitted))
        warnings = _dedupe_warnings(warnings)
        return self.rubrics.create(
            subject_id=self.subject.id,
            paper_job_id=paper_job_id,
            source_document_id=source_document_id,
            source_document_checksum=document_checksum,
            identity={
                "paper_filename": str(job["filename"]),
                "mark_scheme_filename": str(document.get("filename") or ""),
                "pair_key": document_pair or job_pair,
            },
            parser_model=self.settings.grading_model,
            warnings=warnings,
            criteria=criteria,
        )

    def generate(self, *, paper_job_id: str) -> dict[str, object]:
        job = self.papers.get(paper_job_id)
        if job is None or job["subject_code"] != self.subject.subject_code:
            raise LookupError("试卷作答任务不存在")
        if job["status"] not in {"completed", "partial_failed"}:
            raise ValueError("只能为已完成作答的试卷生成评分标准")
        questions = self.papers.questions(paper_job_id)
        if not questions:
            raise ValueError("试卷任务没有可评分题目")

        course_context = json.dumps(
            {
                "course": self.subject.pack.title,
                "subject_code": self.subject.subject_code,
                "units": [
                    {"code": unit.code, "title": unit.title, "strand": unit.strand}
                    for unit in self.subject.pack.unit_rules
                ],
            },
            ensure_ascii=False,
        )
        model = self.structured_model or _structured_model(self.settings)
        with ThreadPoolExecutor(max_workers=min(4, len(questions))) as executor:
            payloads = list(
                executor.map(
                    lambda question: _generate_question_rubric(
                        model,
                        self.settings,
                        question,
                        course_context,
                    ),
                    questions,
                )
            )

        criteria: list[dict[str, object]] = []
        warnings = ["该评分标准由 AI 根据试卷与课程上下文生成，必须由教师逐条审核确认。"]
        for question, payload in zip(questions, payloads, strict=True):
            number = str(question["number"])
            mapped = _map_criteria_to_questions(payload, {number})
            try:
                requirements = json.loads(str(question.get("requirements_json") or "{}"))
            except json.JSONDecodeError:
                requirements = {}
            expected_marks = requirements.get("total_marks")
            if expected_marks is not None:
                actual_marks = sum(float(str(item["max_marks"])) for item in mapped)
                if abs(actual_marks - float(str(expected_marks))) > 1e-9:
                    raise ValueError(
                        f"AI 生成的第 {number} 题评分标准合计 {actual_marks:g} 分，"
                        f"与题面 {float(str(expected_marks)):g} 分不一致"
                    )
            criteria.extend(mapped)
            warnings.extend(payload.warnings)
        if not criteria:
            raise ValueError("AI 未能生成可审核的评分原子")

        markdown_lines = [
            "# AI Generated Provisional Mark Scheme",
            "",
            "> This draft is not an official mark scheme and requires teacher confirmation.",
            "",
        ]
        for item in criteria:
            mark_label = item.get("mark_type") or f"{float(str(item['max_marks'])):g} marks"
            markdown_lines.extend(
                [
                    f"## Q{item['question_number']} {item['subpart']}",
                    f"- **{mark_label}** {item['description']}",
                    "",
                ]
            )
        markdown = "\n".join(markdown_lines)
        checksum = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        document_id = str(uuid4())
        self.markdown_cache.write(
            document_id,
            markdown,
            source_checksum=checksum,
        )
        markdown_path = self.markdown_cache.key(
            document_id,
            source_checksum=checksum,
        )
        parsed_identity = parse_exam_identity(
            Path(str(job.get("filename") or "")),
            "question_paper",
            self.subject.pack,
        )
        pair_key = str(parsed_identity.get("pair_key") or f"generated:{paper_job_id}")
        filename = f"AI-generated-mark-scheme-{paper_job_id[:8]}.md"
        self.documents.register_generated_mark_scheme(
            document_id=document_id,
            subject_id=self.subject.id,
            subject_code=self.subject.subject_code,
            filename=filename,
            checksum=checksum,
            pair_key=pair_key,
            markdown_path=markdown_path,
        )
        return self.rubrics.create(
            subject_id=self.subject.id,
            paper_job_id=paper_job_id,
            source_document_id=document_id,
            source_document_checksum=checksum,
            identity={
                "paper_filename": str(job["filename"]),
                "mark_scheme_filename": filename,
                "pair_key": pair_key,
                "source_kind": "ai_generated",
            },
            parser_model=self.settings.grading_model,
            warnings=_dedupe_warnings(warnings),
            criteria=criteria,
        )

    def papers_ready_for_grading(
        self,
        *,
        paper_unit_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [
            {
                "job_id": row["id"],
                "filename": row["filename"],
                "display_name": row.get("display_name"),
                "paper_unit_id": row.get("paper_unit_id"),
                "question_paper_document_id": row.get("question_paper_document_id"),
                "unit_code": row["unit_code"],
                "status": row["status"],
                "total_questions": row["total_questions"],
                "completed_questions": row["completed_questions"],
                "failed_questions": row["failed_questions"],
                "updated_at": row["updated_at"],
            }
            for row in self.papers.recent_for_subject(self.subject.subject_code)
            if paper_unit_id is None or row.get("paper_unit_id") == paper_unit_id
        ]

    def list_for_paper(self, paper_job_id: str) -> list[dict[str, object]]:
        return self.rubrics.list_for_paper(paper_job_id, subject_id=self.subject.id)

    def get(self, rubric_id: str) -> dict[str, object]:
        return self.rubrics.get(rubric_id, subject_id=self.subject.id)

    def review_criterion(
        self,
        rubric_id: str,
        criterion_id: str,
        *,
        review_status: str,
        reviewer: str,
        note: str | None,
        updates: Mapping[str, object],
    ) -> dict[str, object]:
        return self.rubrics.review_criterion(
            rubric_id,
            criterion_id,
            subject_id=self.subject.id,
            review_status=review_status,
            reviewer=reviewer,
            note=note,
            updates=updates,
        )

    def review_criteria_batch(
        self,
        rubric_id: str,
        request: BatchReviewRubricCriteriaRequest,
    ) -> dict[str, object]:
        criterion_ids = [decision.criterion_id for decision in request.decisions]
        if len(set(criterion_ids)) != len(criterion_ids):
            raise ValueError("批量审核请求包含重复的评分原子")
        decisions = [
            {
                "criterion_id": decision.criterion_id,
                "review_status": decision.review_status,
                "note": decision.note,
                "updates": (
                    decision.updates.model_dump(exclude_unset=True)
                    if decision.updates is not None
                    else {}
                ),
                **(
                    {"expected_criterion_fingerprint": (decision.expected_criterion_fingerprint)}
                    if decision.expected_criterion_fingerprint is not None
                    else {}
                ),
            }
            for decision in request.decisions
        ]
        return self.rubrics.review_criteria_batch(
            rubric_id,
            subject_id=self.subject.id,
            reviewer=request.reviewer,
            decisions=decisions,
        )

    def ai_review_criteria(
        self,
        rubric_id: str,
        request: AiReviewRubricCriteriaRequest,
    ) -> dict[str, object]:
        criterion_ids = request.criterion_ids
        if len(set(criterion_ids)) != len(criterion_ids):
            raise ValueError("AI 审核请求包含重复的评分原子")
        rubric = self.rubrics.get(rubric_id, subject_id=self.subject.id)
        if rubric.get("subject_id") != self.subject.id:
            raise LookupError("评分规则不存在")
        if rubric.get("status") != "draft":
            raise RubricConflictError("只能审核草稿评分规则")

        criteria = rubric.get("criteria")
        if not isinstance(criteria, list):
            raise ValueError("评分规则缺少评分原子")
        criteria_by_id = {
            str(item["id"]): item
            for item in criteria
            if isinstance(item, dict) and item.get("id") is not None
        }
        missing_ids = [
            criterion_id for criterion_id in criterion_ids if criterion_id not in criteria_by_id
        ]
        if missing_ids:
            raise LookupError("评分原子不存在：" + "、".join(missing_ids))
        selected = [criteria_by_id[criterion_id] for criterion_id in criterion_ids]

        paper_job_id = str(rubric["paper_job_id"])
        job = self.papers.get(paper_job_id)
        if job is None or job.get("subject_code") != self.subject.subject_code:
            raise LookupError("试卷作答任务不存在")
        document = self._require_matching_rubric_source(
            rubric,
            self.documents.get(str(rubric["source_document_id"])),
        )

        grouped: dict[str, list[dict[str, object]]] = {}
        for criterion in selected:
            number = str(criterion["question_number"])
            grouped.setdefault(number, []).append(criterion)
        question_rows = self.papers.questions(paper_job_id)
        questions_by_number = {str(question["number"]): question for question in question_rows}
        missing_questions = [number for number in grouped if number not in questions_by_number]
        if missing_questions:
            raise ValueError("评分原子无法映射到试卷题号：" + "、".join(missing_questions))

        mark_scheme = self._document_markdown(
            document,
            expected_checksum=str(rubric["source_document_checksum"]),
        )
        model = self.structured_model or _structured_model(self.settings)
        groups = [
            (questions_by_number[number], grouped[number])
            for number in questions_by_number
            if number in grouped
        ]
        try:
            with ThreadPoolExecutor(max_workers=min(4, len(groups))) as executor:
                payloads = list(
                    executor.map(
                        lambda group: _review_question_criteria(
                            model,
                            self.settings,
                            group[0],
                            mark_scheme,
                            group[1],
                        ),
                        groups,
                    )
                )
        except AiReviewModelError:
            raise
        except Exception as error:
            raise AiReviewModelError("AI 评分原子审核失败") from error

        reviews = [review for payload in payloads for review in payload]
        output_ids = [str(review["criterion_id"]) for review in reviews]
        if Counter(output_ids) != Counter(criterion_ids):
            raise AiReviewModelError("AI 审核结果未覆盖全部评分原子")
        return self.rubrics.record_ai_reviews(
            rubric_id,
            subject_id=self.subject.id,
            reviews=reviews,
            model=str(getattr(model, "model_name", self.settings.grading_model)),
        )

    def confirm(self, rubric_id: str, *, reviewer: str) -> dict[str, object]:
        return self.rubrics.confirm(
            rubric_id,
            subject_id=self.subject.id,
            reviewer=reviewer,
        )

    def grade_question(
        self,
        paper_job_id: str,
        position: int,
        *,
        rubric_set_id: str,
    ) -> GradeResponse:
        job = self.papers.get(paper_job_id)
        if job is None or job["subject_code"] != self.subject.subject_code:
            raise LookupError("试卷作答任务不存在")
        rubric = self.rubrics.get(rubric_set_id, subject_id=self.subject.id)
        if rubric["paper_job_id"] != paper_job_id or rubric["subject_id"] != self.subject.id:
            raise ValueError("评分规则不属于当前试卷")
        if rubric["status"] != "confirmed":
            raise ValueError("评分规则尚未人工确认")
        question = next(
            (row for row in self.papers.questions(paper_job_id) if row["position"] == position),
            None,
        )
        if question is None:
            raise LookupError("题目记录不存在")
        if question["status"] != "completed" or not question.get("answer_json"):
            raise ValueError("该题尚无可评分的完整作答")
        answer = PaperQuestionAnswer.model_validate_json(str(question["answer_json"]))
        criteria = self.rubrics.accepted_for_question(
            rubric_set_id,
            str(question["number"]),
            subject_id=self.subject.id,
        )
        if not criteria:
            raise ValueError("该题没有已接受的评分原子")
        max_marks = sum(float(item["max_marks"]) for item in criteria)
        mark_scheme = json.dumps(
            [_criterion_scoring_payload(item) for item in criteria],
            ensure_ascii=False,
            indent=2,
        )
        result = self.grading.grade(
            GradeRequest(
                answer_markdown=answer.answer_markdown,
                question_ref=f"{job.get('pair_key') or paper_job_id}:Q{question['number']}",
                question_markdown=str(question["question_markdown"]),
                mark_scheme_markdown=mark_scheme,
                max_marks=max_marks,
                unit_code=job.get("unit_code"),
                knowledge_codes=[
                    str(item) for item in json.loads(question["knowledge_codes_json"])
                ],
            ),
            confirmed_criteria=[_criterion_scoring_payload(item) for item in criteria],
            answer_diagrams=answer.diagrams,
            answer_images=answer.images,
        )
        self.assessments.link_context(
            result.assessment_id,
            paper_job_id=paper_job_id,
            question_position=position,
            rubric_set_id=rubric_set_id,
            knowledge_base_version_ids=[
                str(item) for item in json.loads(job["knowledge_base_version_ids_json"] or "[]")
            ],
            graph_version_id=job.get("graph_version_id"),
        )
        return result

    def assessments_for_paper(self, paper_job_id: str) -> list[dict[str, object]]:
        job = self.papers.get(paper_job_id)
        if job is None or job["subject_code"] != self.subject.subject_code:
            raise LookupError("试卷作答任务不存在")
        return self.assessments.for_paper(
            paper_job_id,
            subject_code=self.subject.subject_code,
        )

    def grading_overview(
        self,
        paper_job_id: str,
        rubric_set_id: str,
    ) -> dict[str, object]:
        job = self.papers.get(paper_job_id)
        if job is None or job.get("subject_code") != self.subject.subject_code:
            raise LookupError("试卷作答任务不存在")
        rubric = self.rubrics.get(rubric_set_id, subject_id=self.subject.id)
        if (
            rubric.get("paper_job_id") != paper_job_id
            or rubric.get("subject_id") != self.subject.id
        ):
            raise ValueError("评分规则不属于当前试卷")
        if rubric.get("status") != "confirmed":
            raise ValueError("评分规则尚未人工确认")

        questions = self.papers.questions(paper_job_id)
        criteria = rubric.get("criteria")
        if not isinstance(criteria, list):
            criteria = []
        accepted_available: dict[str, float] = {}
        for criterion in criteria:
            if not isinstance(criterion, Mapping) or criterion.get("review_status") != "accepted":
                continue
            number = str(criterion["question_number"])
            accepted_available[number] = accepted_available.get(number, 0.0) + float(
                criterion["max_marks"]
            )

        latest_by_position: dict[int, dict[str, object]] = {}
        for assessment in self.assessments.for_paper(
            paper_job_id,
            subject_code=self.subject.subject_code,
        ):
            if assessment.get("rubric_set_id") != rubric_set_id:
                continue
            position_value = assessment.get("question_position")
            if position_value is None:
                continue
            position = int(position_value)
            current = latest_by_position.get(position)
            candidate_key = (
                str(assessment.get("created_at") or ""),
                str(assessment.get("id") or ""),
            )
            current_key = (
                (
                    str(current.get("created_at") or ""),
                    str(current.get("id") or ""),
                )
                if current is not None
                else None
            )
            if current_key is None or candidate_key > current_key:
                latest_by_position[position] = assessment

        overview_questions: list[dict[str, object]] = []
        error_counts: Counter[str] = Counter()
        overall_suggestions: list[str] = []
        seen_suggestions: set[str] = set()
        total_awarded = 0.0
        total_available = 0.0
        status_counts = Counter[str]()

        for question in sorted(questions, key=lambda item: int(item["position"])):
            position = int(question["position"])
            number = str(question["number"])
            assessment = latest_by_position.get(position)
            if assessment is None:
                available = accepted_available.get(number, 0.0)
                overview_questions.append(
                    {
                        "position": position,
                        "question_number": number,
                        "status": "unassessed",
                        "awarded": None,
                        "available": available,
                        "confidence": None,
                        "error_types": [],
                        "suggestions": [],
                    }
                )
                total_available += available
                continue

            status = str(assessment["status"])
            awarded_value = assessment.get("total_awarded")
            available_value = assessment.get("total_available")
            confidence_value = assessment.get("confidence")
            if (
                isinstance(awarded_value, bool)
                or not isinstance(awarded_value, (int, float))
                or isinstance(available_value, bool)
                or not isinstance(available_value, (int, float))
                or isinstance(confidence_value, bool)
                or not isinstance(confidence_value, (int, float))
            ):
                raise ValueError("评分结果缺少有效的分值或置信度")
            awarded = float(awarded_value)
            available = float(available_value)
            confidence = float(confidence_value)
            error_types, suggestions = _assessment_diagnostics(assessment.get("result"))
            error_counts.update(error_types)
            for suggestion in suggestions:
                if suggestion not in seen_suggestions:
                    seen_suggestions.add(suggestion)
                    overall_suggestions.append(suggestion)
            status_counts[status] += 1
            total_awarded += awarded
            total_available += available
            overview_questions.append(
                {
                    "position": position,
                    "question_number": number,
                    "status": status,
                    "awarded": awarded,
                    "available": available,
                    "confidence": confidence,
                    "error_types": error_types,
                    "suggestions": suggestions,
                }
            )

        error_order = {value: index for index, value in enumerate(_ERROR_TYPE_ORDER)}
        common_error_types = sorted(
            error_counts,
            key=lambda value: (
                -error_counts[value],
                error_order.get(value, len(error_order)),
                value,
            ),
        )
        completed_questions = sum(status_counts.values())
        total_questions = len(questions)
        percentage = (
            round(total_awarded / total_available * 100, 2) if total_available > 0 else None
        )
        identity = rubric.get("identity")
        rubric_pair = str(identity.get("pair_key") or "") if isinstance(identity, Mapping) else ""

        def is_deferred(item: dict[str, object]) -> bool:
            if item.get("status") != "pending_review":
                return False
            result = item.get("result")
            warnings = result.get("warnings", []) if isinstance(result, Mapping) else []
            return item.get("confidence") == 0 or any("暂缓授分" in str(w) for w in warnings)

        deferred = any(is_deferred(item) for item in latest_by_position.values())
        grade_estimate = estimate_unit_grade(
            subject_code=self.subject.subject_code,
            pair_key=str(job.get("pair_key") or ""),
            rubric_pair_key=rubric_pair,
            awarded=total_awarded,
            available=total_available,
            complete=total_questions > 0 and completed_questions == total_questions,
            pending_review=status_counts["pending_review"] > 0,
            deferred=deferred,
        )
        return {
            "grade_estimate": grade_estimate.model_dump(),
            "paper_job_id": paper_job_id,
            "rubric_set_id": rubric_set_id,
            "total_awarded": total_awarded,
            "total_available": total_available,
            "percentage": percentage,
            "completed_questions": completed_questions,
            "total_questions": total_questions,
            "pending_review_count": status_counts["pending_review"],
            "confirmed_count": status_counts["confirmed"],
            "overridden_count": status_counts["overridden"],
            "incomplete": completed_questions < total_questions,
            "overall_suggestion": _overall_suggestion(
                completed_questions=completed_questions,
                total_questions=total_questions,
                percentage=percentage,
                common_error_types=common_error_types,
                suggestions=overall_suggestions,
            ),
            "common_error_types": common_error_types,
            "questions": overview_questions,
        }
