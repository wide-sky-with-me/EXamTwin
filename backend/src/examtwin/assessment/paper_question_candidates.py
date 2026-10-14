"""Pure candidate rules; model calls and source reconciliation stay in paper_answering.

Decision: .agents/notes/implemented/simplification/2026-10-14-paper-question-candidate-rules.md
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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


class _QuestionRepairGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: str = Field(min_length=1, max_length=32)
    candidate_indexes: list[int] = Field(min_length=1)
    preferred_candidate_index: int | None = Field(default=None, ge=0)


class _QuestionRepairPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    groups: list[_QuestionRepairGroup] = Field(min_length=1)


class _QuestionCandidateConflict(ValueError):
    """A same-source overlap conflict that may be resolved against the trusted source."""

    def __init__(self, message: str, *, question_numbers: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.question_numbers = question_numbers


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
