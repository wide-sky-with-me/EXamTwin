from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from examtwin.assessment.assessment_repository import AssessmentRepository
from examtwin.assessment.grading import GradingService
from examtwin.assessment.paper_job_repository import PaperJobRepository
from examtwin.assessment.rubric_repository import RubricRepository
from examtwin.contracts.grading import GradeRequest, GradeResponse
from examtwin.contracts.papers import PaperQuestionAnswer
from examtwin.knowledge.public import CorpusRepository, parse_exam_identity
from examtwin.platform.agent_runtime import (
    StructuredModelPort,
    StructuredTask,
    StructuredTaskRunner,
)
from examtwin.platform.cache_paths import MarkdownCacheMissing, resolve_markdown_cache_path
from examtwin.platform.config import Settings
from examtwin.platform.structured_model import LiteLLMStructuredModel
from examtwin.subjects.public import SubjectContext


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


class RubricExtractionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria: list[RubricCriterionDraft] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


_QUESTION_LABEL = re.compile(
    r"^\s*(?:question|q)?\s*[:#]?\s*0*(?P<number>\d+)"
    r"(?P<subpart>\s*(?:[._/-]\s*)?\(?[a-z0-9]+\)?)?\s*$",
    re.IGNORECASE,
)


def _question_label(value: str) -> tuple[str, str | None] | None:
    match = _QUESTION_LABEL.fullmatch(value)
    if match is None:
        return None
    subpart = match.group("subpart")
    if subpart:
        subpart = re.sub(r"^[\s._/-]+", "", subpart).strip().strip("()")
    return str(int(match.group("number"))), subpart or None


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
        if item.question_number in valid_numbers:
            criteria.append(item.model_dump())
            continue
        label = _question_label(item.question_number)
        if label is None:
            continue
        mapped_number = canonical_numbers.get(label[0])
        if mapped_number is None:
            continue
        values = item.model_dump()
        values["question_number"] = mapped_number
        if values["subpart"] == "whole" and label[1] is not None:
            values["subpart"] = label[1]
        criteria.append(values)
    return criteria


def _structured_model(settings: Settings) -> StructuredModelPort:
    credential = settings.llm_provider_api_key
    if credential is None or not credential.get_secret_value():
        raise RuntimeError("LLM credential is required for mark-scheme parsing")
    return LiteLLMStructuredModel(
        model=settings.grading_model,
        api_base=settings.llm_provider_base_url,
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
    ) -> None:
        self.settings = settings
        self.subject = subject
        self.documents = documents
        self.papers = papers
        self.rubrics = rubrics
        self.assessments = assessments
        self.grading = grading
        self.structured_model = structured_model

    def _document_markdown(self, document: dict[str, object]) -> str:
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

    def create(self, *, paper_job_id: str, source_document_id: str) -> dict[str, object]:
        job = self.papers.get(paper_job_id)
        if job is None or job["subject_code"] != self.subject.subject_code:
            raise LookupError("试卷作答任务不存在")
        if job["status"] not in {"completed", "partial_failed"}:
            raise ValueError("只能为已完成作答的试卷创建评分规则")
        document = self.documents.get(source_document_id)
        if document is None or document.get("subject_code") != self.subject.subject_code:
            raise LookupError("评分方案文档不存在")
        if document.get("source_type") != "mark_scheme":
            raise ValueError("所选文档不是 Mark Scheme")
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
        question_outline = "\n".join(
            f"QUESTION {row['number']}:\n{str(row['question_markdown'])[:3000]}"
            for row in questions
        )
        mark_scheme = self._document_markdown(document)
        system_prompt = (
            "You extract an auditable typed rubric from an official examination mark scheme. "
            "Return one criterion per indivisible mark atom. Preserve M/A/B/FT labels, explicit "
            "dependencies, alternative methods, accuracy, units, and levels descriptors. Use "
            "point_based for atomic marks and levels_based only for holistic level bands. "
            "question_number must exactly equal one QUESTION label supplied by the caller. "
            "Never invent a mark, infer from a model answer, or merge separate atoms."
        )
        user_content = (
            f"PAPER QUESTIONS:\n{question_outline[:24000]}\n\n"
            f"OFFICIAL MARK SCHEME:\n{mark_scheme[:60000]}"
        )
        payload = StructuredTaskRunner(
            self.structured_model or _structured_model(self.settings)
        ).run(
            StructuredTask(system_prompt=system_prompt, user_content=user_content),
            RubricExtractionDraft,
            timeout=self.settings.grading_timeout,
        )
        valid_numbers = {str(row["number"]) for row in questions}
        criteria = _map_criteria_to_questions(payload, valid_numbers)
        if not criteria:
            raise ValueError("评分方案未能映射到试卷题号")
        warnings = list(payload.warnings)
        omitted = sorted(valid_numbers - {str(item["question_number"]) for item in criteria})
        if omitted:
            warnings.append("未抽取到评分原子的题目：" + "、".join(omitted))
        return self.rubrics.create(
            subject_id=self.subject.id,
            paper_job_id=paper_job_id,
            source_document_id=source_document_id,
            identity={
                "paper_filename": str(job["filename"]),
                "mark_scheme_filename": str(document.get("filename") or ""),
                "pair_key": document_pair or job_pair,
            },
            parser_model=self.settings.grading_model,
            warnings=warnings,
            criteria=criteria,
        )

    def papers_ready_for_grading(self) -> list[dict[str, object]]:
        return [
            {
                "job_id": row["id"],
                "filename": row["filename"],
                "unit_code": row["unit_code"],
                "status": row["status"],
                "total_questions": row["total_questions"],
                "completed_questions": row["completed_questions"],
                "failed_questions": row["failed_questions"],
                "updated_at": row["updated_at"],
            }
            for row in self.papers.recent_for_subject(self.subject.subject_code)
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
        mark_scheme = json.dumps(criteria, ensure_ascii=False, indent=2)
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
            )
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
