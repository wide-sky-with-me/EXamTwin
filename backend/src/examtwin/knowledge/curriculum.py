from __future__ import annotations

import hashlib
import html
import json
import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypedDict

from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader

from examtwin.subjects.public import SubjectPack, UnitRule

EXTRACTOR_VERSION = "structured-markdown-curriculum-v1"
MINERU_MARKDOWN_PROJECTION = "mineru-markdown-v1"
PDF_TEXT_PROJECTION = "pdf-text-layer-v1"


class _RawTopicRecord(TypedDict):
    code: str
    title: str
    page: int
    unit: UnitRule | None
    order: int


class CurriculumUnit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    title: str
    strand: str
    page: int


class CurriculumTopic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    title: str
    unit_code: str
    strand: str
    page: int
    order: int
    syllabus_complexity: float = Field(ge=0, le=1)
    prerequisite_depth: int = Field(ge=0, le=12)
    cognitive_demand: float = Field(ge=0, le=1)
    solution_steps: int = Field(ge=1, le=20)


class CurriculumObjective(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    parent: str
    title: str
    description: str = ""
    page: int | None = None
    index: int


class CurriculumCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_pack_id: str
    subject_code: str
    source_document_id: str
    source_ref: str
    input_hash: str
    extractor_version: str = EXTRACTOR_VERSION
    units: list[CurriculumUnit]
    topics: list[CurriculumTopic]
    objectives: list[CurriculumObjective]
    warnings: list[str] = Field(default_factory=list)

    @property
    def content_hash(self) -> str:
        payload = self.model_dump(exclude={"warnings"})
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()


class CurriculumValidation(BaseModel):
    passed: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metrics: dict[str, int | float] = Field(default_factory=dict)


@dataclass(frozen=True)
class CurriculumExtraction:
    """One selected, validated semantic projection of a syllabus source."""

    projection: str
    candidate: CurriculumCandidate
    validation: CurriculumValidation


class CurriculumExtractor(Protocol):
    key: str

    def extract(
        self,
        markdown: str,
        subject_pack: SubjectPack,
        *,
        source_document_id: str,
        source_ref: str,
        input_hash: str,
    ) -> CurriculumCandidate: ...


def _plain_text(cell: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", cell, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    text = re.sub(r"(?<=[.!?;])(?=[A-Z])", " ", text)
    text = re.sub(r"(?<=:)(?=[A-Za-z])", " ", text)
    replacements = {
        r"\bwillnotbe\b": "will not be",
        r"\bisnotrequired\b": "is not required",
        r"\bnotrequired\b": "not required",
        r"\borcompleting\b": "or completing",
        r"\bwherenis\b": "where n is",
        r"\basthe\b": "as the",
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def _topic_features(
    objectives: list[CurriculumObjective],
) -> tuple[float, int, float, int]:
    combined = " ".join(f"{item.title} {item.description}" for item in objectives).lower()
    count_score = min(1.0, math.log1p(len(objectives)) / math.log(21))
    detail_score = min(
        1.0,
        sum(len(item.description) for item in objectives) / max(1, len(objectives) * 220),
    )
    high_demand = len(
        re.findall(
            r"\b(prove|derive|evaluate|analyse|analyze|justify|interpret|model|compare)\b",
            combined,
        )
    )
    cognitive = min(0.9, 0.35 + 0.08 * min(5, high_demand) + 0.12 * detail_score)
    complexity = min(0.9, 0.3 + 0.4 * count_score + 0.2 * detail_score)
    steps = max(2, min(10, round(2 + 4 * cognitive + 2 * count_score)))
    # Sequence position is not prerequisite evidence. Keep depth at zero until
    # an explicit relation stage publishes a sourced prerequisite observation.
    prerequisite_depth = 0
    return complexity, prerequisite_depth, cognitive, steps


class StructuredMarkdownCurriculumExtractor:
    key = "structured-markdown-v1"

    def extract(
        self,
        markdown: str,
        subject_pack: SubjectPack,
        *,
        source_document_id: str,
        source_ref: str,
        input_hash: str,
    ) -> CurriculumCandidate:
        current_page: int | None = None
        current_topic: str | None = None
        raw_topics: list[_RawTopicRecord] = []
        topics_by_code: dict[str, _RawTopicRecord] = {}
        objective_counts: Counter[str] = Counter()
        objectives: list[CurriculumObjective] = []
        warnings: list[str] = []
        topic_pattern = subject_pack.topic_heading_pattern()
        text_normalizer = subject_pack.curriculum_normalizer
        pending_text: list[str] = []
        pending_page: int | None = None

        def append_objective(
            topic_code: str,
            raw_title: str,
            description: str = "",
            *,
            page: int | None = None,
        ) -> None:
            title = _plain_text(raw_title)
            detail = _plain_text(description)
            if not title or title.lower() in {"content", "additional information"}:
                return
            if len(title) < 3:
                return
            objective_counts[topic_code] += 1
            index = objective_counts[topic_code]
            topic = topics_by_code[topic_code]
            objectives.append(
                CurriculumObjective(
                    code=f"{topic_code}.O{index:02d}",
                    parent=topic_code,
                    title=text_normalizer.objective_title(str(topic["title"]), title),
                    description=detail,
                    page=page,
                    index=index,
                )
            )

        def flush_pending() -> None:
            nonlocal pending_text, pending_page
            if current_topic is not None and pending_text:
                append_objective(
                    current_topic,
                    " ".join(pending_text),
                    page=pending_page,
                )
            pending_text = []
            pending_page = None

        def is_page_boilerplate(value: str) -> bool:
            lowered = value.lower()
            return (
                not value
                or value.isdigit()
                or lowered.startswith("visit oxfordaqa")
                or lowered.startswith("oxfordaqa international")
                or lowered.startswith("for international as exams")
                or lowered
                in {"content additional information", "content", "additional information"}
            )

        for line in markdown.splitlines():
            stripped = line.strip()
            page_match = re.match(r"^## Page (\d+)", stripped)
            if page_match:
                flush_pending()
                current_page = int(page_match.group(1))
                continue
            topic_match = topic_pattern.match(stripped)
            if topic_match:
                flush_pending()
                code = topic_match.group("code")
                title = re.sub(r"\s+", " ", topic_match.group("title")).strip()
                unit = subject_pack.resolve_topic_unit(code)
                if code in topics_by_code:
                    warnings.append(f"duplicate topic heading ignored: {code}")
                    current_topic = code
                    continue
                record: _RawTopicRecord = {
                    "code": code,
                    "title": title,
                    "page": current_page or 0,
                    "unit": unit,
                    "order": len(raw_topics) + 1,
                }
                raw_topics.append(record)
                topics_by_code[code] = record
                current_topic = code
                continue
            if re.match(r"^#{1,6}\s+", stripped):
                flush_pending()
                current_topic = None
                continue
            # A numbered intermediate section (for example 3.2.2) ends the
            # previous leaf topic. The configured topic regex still decides
            # which numbered headings are real knowledge topics.
            if re.match(r"^\d+(?:\.\d+){1,2}\s+", stripped):
                flush_pending()
                current_topic = None
                continue
            if current_topic is None or is_page_boilerplate(stripped):
                continue

            html_rows = re.findall(r"<tr[^>]*>(.*?)</tr>", line, flags=re.IGNORECASE)
            if html_rows:
                flush_pending()
            for row in html_rows:
                cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.IGNORECASE)
                if not cells:
                    continue
                append_objective(
                    current_topic,
                    cells[0],
                    cells[1] if len(cells) > 1 else "",
                    page=current_page,
                )
            if html_rows:
                continue

            if stripped.startswith("|") and stripped.endswith("|"):
                flush_pending()
                cells = [cell.strip() for cell in stripped.strip("|").split("|")]
                if cells and not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                    append_objective(
                        current_topic,
                        cells[0],
                        cells[1] if len(cells) > 1 else "",
                        page=current_page,
                    )
                continue

            bullet = re.match(r"^(?:[-*•]\s+)(.+)$", stripped)
            paragraph = re.match(
                r"^(Students?\s+(?:should|will|are|must|need)|A detailed knowledge\b)(.+)$",
                stripped,
                flags=re.IGNORECASE,
            )
            if bullet or paragraph:
                flush_pending()
                pending_text = [bullet.group(1) if bullet else stripped]
                pending_page = current_page
                continue
            if pending_text:
                pending_text.append(stripped)

        flush_pending()

        objectives_by_topic: dict[str, list[CurriculumObjective]] = {
            code: [] for code in topics_by_code
        }
        for objective in objectives:
            objectives_by_topic.setdefault(objective.parent, []).append(objective)

        topics: list[CurriculumTopic] = []
        for record in raw_topics:
            code = str(record["code"])
            unit = record["unit"]
            if unit is None:
                unit_code = "UNMAPPED"
                strand = "Unmapped"
            else:
                unit_code = unit.code
                strand = unit.strand
            complexity, depth, cognitive, steps = _topic_features(
                objectives_by_topic.get(code, []),
            )
            topics.append(
                CurriculumTopic(
                    code=code,
                    title=str(record["title"]),
                    unit_code=unit_code,
                    strand=strand,
                    page=int(record["page"]),
                    order=int(record["order"]),
                    syllabus_complexity=complexity,
                    prerequisite_depth=depth,
                    cognitive_demand=cognitive,
                    solution_steps=steps,
                )
            )

        return CurriculumCandidate(
            subject_pack_id=subject_pack.id,
            subject_code=subject_pack.subject_code,
            source_document_id=source_document_id,
            source_ref=source_ref,
            input_hash=input_hash,
            units=[
                CurriculumUnit(
                    code=rule.code,
                    title=rule.title,
                    strand=rule.strand,
                    page=rule.source_page,
                )
                for rule in subject_pack.unit_rules
            ],
            topics=topics,
            objectives=objectives,
            warnings=warnings,
        )


EXTRACTORS: dict[str, CurriculumExtractor] = {
    StructuredMarkdownCurriculumExtractor.key: StructuredMarkdownCurriculumExtractor()
}


def get_curriculum_extractor(subject_pack: SubjectPack) -> CurriculumExtractor:
    try:
        return EXTRACTORS[subject_pack.extractor_key]
    except KeyError as error:
        raise ValueError(
            f"Unknown curriculum extractor {subject_pack.extractor_key!r} for {subject_pack.id}"
        ) from error


def validate_curriculum_candidate(
    candidate: CurriculumCandidate,
    subject_pack: SubjectPack,
) -> CurriculumValidation:
    errors: list[str] = []
    warnings = list(candidate.warnings)
    topic_codes = [topic.code for topic in candidate.topics]
    objective_codes = [objective.code for objective in candidate.objectives]
    unit_codes = {unit.code for unit in candidate.units}
    expected_units = {rule.code for rule in subject_pack.unit_rules}
    if len(candidate.topics) < subject_pack.minimum_topics:
        errors.append(
            f"expected at least {subject_pack.minimum_topics} topics, found {len(candidate.topics)}"
        )
    if len(candidate.objectives) < subject_pack.minimum_objectives:
        errors.append(
            "expected at least "
            f"{subject_pack.minimum_objectives} objectives, found {len(candidate.objectives)}"
        )
    if len(topic_codes) != len(set(topic_codes)):
        errors.append("duplicate topic codes")
    if len(objective_codes) != len(set(objective_codes)):
        errors.append("duplicate objective codes")
    if unit_codes != expected_units:
        errors.append(
            f"unit mismatch; missing={sorted(expected_units - unit_codes)}, "
            f"unexpected={sorted(unit_codes - expected_units)}"
        )
    topic_code_set = set(topic_codes)
    unmapped = sorted(topic.code for topic in candidate.topics if topic.unit_code == "UNMAPPED")
    if unmapped:
        errors.append(f"unmapped topics: {unmapped}")
    invalid_parents = sorted(
        {
            objective.parent
            for objective in candidate.objectives
            if objective.parent not in topic_code_set
        }
    )
    if invalid_parents:
        errors.append(f"unknown objective parents: {invalid_parents}")
    empty_topics = sorted(
        topic.code
        for topic in candidate.topics
        if not any(objective.parent == topic.code for objective in candidate.objectives)
    )
    if empty_topics:
        warnings.append(f"topics without extracted objectives: {empty_topics}")
    counts_by_unit = Counter(topic.unit_code for topic in candidate.topics)
    missing_unit_content = sorted(code for code in expected_units if counts_by_unit[code] == 0)
    if missing_unit_content:
        errors.append(f"units without topics: {missing_unit_content}")
    return CurriculumValidation(
        passed=not errors,
        errors=errors,
        warnings=warnings,
        metrics={
            "units": len(candidate.units),
            "topics": len(candidate.topics),
            "objectives": len(candidate.objectives),
            "topics_without_objectives": len(empty_topics),
        },
    )


def pdf_text_curriculum_projection(pdf_path: Path) -> str:
    """Preserve PDF text lines for syllabus semantics without replacing MinerU RAG Markdown."""

    reader = PdfReader(str(pdf_path))
    return "\n".join(
        f"## Page {page_number}\n{page.extract_text() or ''}"
        for page_number, page in enumerate(reader.pages, start=1)
    )


def select_curriculum_projection(
    projections: Sequence[tuple[str, str]],
    subject_pack: SubjectPack,
    *,
    source_document_id: str,
    source_ref: str,
) -> CurriculumExtraction:
    """Use canonical MinerU Markdown when publishable, otherwise choose a safer projection.

    MinerU intentionally keeps a table as one source block for RAG. Some PDF tables omit cell
    line breaks in their HTML serialization, however, which can collapse many syllabus outcomes
    into one row. A native text-layer projection is therefore allowed as a semantic fallback while
    the canonical Markdown remains unchanged and available for citation.
    """

    if not projections:
        raise ValueError("At least one curriculum projection is required")
    extractor = get_curriculum_extractor(subject_pack)
    results: list[CurriculumExtraction] = []
    for projection, text in projections:
        input_hash = hashlib.sha256(f"{projection}\0{text}".encode()).hexdigest()
        candidate = extractor.extract(
            text,
            subject_pack,
            source_document_id=source_document_id,
            source_ref=source_ref,
            input_hash=input_hash,
        )
        validation = validate_curriculum_candidate(candidate, subject_pack)
        result = CurriculumExtraction(
            projection=projection,
            candidate=candidate,
            validation=validation,
        )
        results.append(result)
        if validation.passed and not validation.warnings:
            return result

    def quality(result: CurriculumExtraction) -> tuple[int, int, int, int, int]:
        metrics = result.validation.metrics
        return (
            int(result.validation.passed),
            -len(result.validation.errors),
            int(metrics.get("topics", 0)),
            int(metrics.get("objectives", 0)),
            -len(result.validation.warnings),
        )

    return max(results, key=quality)
