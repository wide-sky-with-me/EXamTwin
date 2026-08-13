from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sympy import simplify

from examtwin.assessment.assessment_repository import AssessmentRepository
from examtwin.assessment.symbolic import parse_safe_expression
from examtwin.contracts.evidence import Citation
from examtwin.contracts.grading import (
    GradeRequest,
    GradeResponse,
    ReviewRequest,
    RubricAward,
    SymbolicCheck,
)
from examtwin.knowledge.public import CorpusRepository
from examtwin.platform.agent_runtime import (
    StructuredModelPort,
    StructuredTask,
    StructuredTaskRunner,
)
from examtwin.platform.cache_paths import MarkdownCacheMissing, resolve_markdown_cache_path
from examtwin.platform.config import Settings
from examtwin.platform.database.session import utcnow
from examtwin.platform.prompts import load_prompt_template
from examtwin.platform.structured_model import LiteLLMStructuredModel
from examtwin.subjects.public import SubjectContext


class GradingRubricDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str
    description: str
    mark_type: str | None = None
    max_marks: float = Field(ge=0)
    awarded: float = Field(ge=0)
    student_evidence: str | None = None
    rationale: str
    confidence: float = Field(ge=0, le=1)
    source_ref: str | None = None
    knowledge_codes: list[str] = Field(default_factory=list)
    error_types: list[
        Literal[
            "conceptual",
            "procedural",
            "calculation",
            "notation",
            "unit",
            "diagram",
            "omission",
        ]
    ] = Field(default_factory=list)
    improvement_suggestion: str | None = None


class GradingDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_available: float = Field(ge=0)
    rubric_awards: list[GradingRubricDraft] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


def _non_verbatim_evidence(payload: GradingDraft, answer_markdown: str) -> list[str]:
    return [
        item.student_evidence
        for item in payload.rubric_awards
        if item.student_evidence and item.student_evidence not in answer_markdown
    ]


def _withheld_non_verbatim_awards(
    payload: GradingDraft,
    answer_markdown: str,
) -> tuple[GradingDraft, list[str]]:
    sanitized = payload.model_copy(deep=True)
    withheld: list[str] = []
    for item in sanitized.rubric_awards:
        if not item.student_evidence or item.student_evidence in answer_markdown:
            continue
        withheld.append(item.criterion_id)
        item.student_evidence = None
        item.awarded = 0
    return sanitized, withheld


def _grading_model(settings: Settings) -> StructuredModelPort:
    credential = settings.llm_provider_api_key
    if credential is None or not credential.get_secret_value():
        raise RuntimeError("LLM credential is required for grading")
    return LiteLLMStructuredModel(
        model=settings.grading_model,
        api_base=settings.llm_provider_base_url,
        api_key=credential.get_secret_value(),
        reasoning_effort=settings.grading_reasoning_effort,
        max_retries=1,
    )


def symbolic_checks(request: GradeRequest) -> list[SymbolicCheck]:
    checks: list[SymbolicCheck] = []
    for item in request.expected_expressions:
        try:
            student = parse_safe_expression(item.student, item.variable)
            expected = parse_safe_expression(item.expected, item.variable)
            equivalent = bool(simplify(student - expected) == 0)
            detail = (
                "CAS found the expressions equivalent."
                if equivalent
                else ("CAS found a non-zero symbolic difference.")
            )
        except Exception as error:
            equivalent = None
            detail = f"CAS check unavailable: {str(error)[:160]}"
        checks.append(
            SymbolicCheck(
                student=item.student,
                expected=item.expected,
                equivalent=equivalent,
                detail=detail,
            )
        )
    return checks


class GradingService:
    def __init__(
        self,
        documents: CorpusRepository,
        assessments: AssessmentRepository,
        settings: Settings,
        subject: SubjectContext,
        *,
        structured_model: StructuredModelPort | None = None,
    ):
        self.settings = settings
        self.documents = documents
        self.assessments = assessments
        self.subject = subject
        self.structured_model = structured_model

    def _document_text(self, row: dict[str, Any]) -> str | None:
        if not row.get("markdown_path"):
            return None
        try:
            markdown_path = resolve_markdown_cache_path(
                self.settings,
                str(row["id"]),
                str(row["markdown_path"]),
            )
            return Path(markdown_path).read_text(encoding="utf-8")
        except (OSError, MarkdownCacheMissing):
            return None

    def _resolve_context(self, request: GradeRequest) -> tuple[str, str, list[Citation], list[str]]:
        question = request.question_markdown
        mark_scheme = request.mark_scheme_markdown
        citations: list[Citation] = []
        warnings: list[str] = []
        pair_key: str | None = None

        if request.question_ref:
            row = self.documents.resolve_reference(
                request.question_ref,
                subject_code=self.subject.subject_code,
            )
            if row:
                pair_key = row.get("pair_key")
                if question is None and row["source_type"] == "question_paper":
                    question = self._document_text(row)
                if row["source_type"] == "mark_scheme" and mark_scheme is None:
                    mark_scheme = self._document_text(row)
                citations.append(
                    Citation(
                        source=row["path"],
                        source_type=row["source_type"],
                        pair_key=pair_key,
                        excerpt=(question or mark_scheme or "")[:360],
                    )
                )
            elif request.question_ref.startswith(f"{self.subject.subject_code}:"):
                pair_key = request.question_ref

        if mark_scheme is None and pair_key:
            rows = self.documents.mark_schemes(
                pair_key,
                subject_code=self.subject.subject_code,
            )
            texts = [text for row in rows if (text := self._document_text(row))]
            if texts:
                mark_scheme = "\n\n".join(texts)
                citations.extend(
                    Citation(
                        source=row["path"],
                        source_type="mark_scheme",
                        pair_key=pair_key,
                        excerpt=(self._document_text(row) or "")[:360],
                    )
                    for row in rows
                )

        if question is None:
            question = f"Question reference: {request.question_ref}"
            warnings.append("Question paper text was not available; reference only.")
        if mark_scheme is None:
            raise ValueError(
                "A mark scheme is required. Provide mark_scheme_markdown or convert the "
                "strictly paired mark scheme into the knowledge base first."
            )
        return question, mark_scheme, citations, warnings

    def grade(self, request: GradeRequest) -> GradeResponse:
        question, mark_scheme, citations, warnings = self._resolve_context(request)
        checks = symbolic_checks(request)
        cas_context = (
            "\n".join(
                f"- {item.student} vs {item.expected}: {item.equivalent} ({item.detail})"
                for item in checks
            )
            or "No independent CAS checks supplied."
        )
        max_marks_context = (
            f"The paper/question maximum is {request.max_marks}."
            if request.max_marks is not None
            else "Derive the maximum only from explicit mark-scheme atoms."
        )
        system_prompt = load_prompt_template("grading/SYSTEM.md")

        user_content = f"""
QUESTION:
{question[:16000]}

MARK SCHEME:
{mark_scheme[:28000]}

STUDENT ANSWER:
{request.answer_markdown[:16000]}

CAS CHECKS:
{cas_context}

MAXIMUM MARKS:
{max_marks_context}

RELEVANT KNOWLEDGE CODES:
{", ".join(request.knowledge_codes) or "None supplied."}
""".strip()
        runner = StructuredTaskRunner(self.structured_model or _grading_model(self.settings))
        task = StructuredTask(system_prompt=system_prompt, user_content=user_content)
        payload = runner.run(task, GradingDraft, timeout=self.settings.grading_timeout)
        invalid_evidence = _non_verbatim_evidence(payload, request.answer_markdown)
        if invalid_evidence:
            payload = runner.run(
                StructuredTask(
                    system_prompt=system_prompt,
                    user_content=(
                        f"{user_content}\n\n"
                        "CORRECTION REQUIRED: Every student_evidence value must be an exact, "
                        "contiguous quote from STUDENT ANSWER. Do not paraphrase evidence."
                    ),
                ),
                GradingDraft,
                timeout=self.settings.grading_timeout,
            )
            payload, withheld = _withheld_non_verbatim_awards(
                payload,
                request.answer_markdown,
            )
            if withheld:
                payload.warnings.append(
                    "模型未能提供学生答案中的逐字证据；相关评分原子已暂缓授分并保留人工复核："
                    + "、".join(withheld)
                )
        awards: list[RubricAward] = []
        for number, item in enumerate(payload.rubric_awards, start=1):
            maximum = max(0.0, item.max_marks)
            awarded = max(0.0, min(maximum, item.awarded))
            awards.append(
                RubricAward(
                    criterion_id=item.criterion_id or str(number),
                    description=item.description,
                    mark_type=item.mark_type,
                    max_marks=maximum,
                    awarded=awarded,
                    student_evidence=item.student_evidence,
                    rationale=item.rationale,
                    confidence=item.confidence,
                    source_ref=item.source_ref,
                    knowledge_codes=item.knowledge_codes,
                    error_types=item.error_types,
                    improvement_suggestion=item.improvement_suggestion,
                )
            )
        if not awards:
            raise ValueError("The model returned no auditable rubric atoms")

        total_available = sum(item.max_marks for item in awards)
        if request.max_marks is not None:
            total_available = request.max_marks
        total_awarded = min(total_available, sum(item.awarded for item in awards))
        confidence = sum(item.confidence * max(item.max_marks, 0.001) for item in awards) / sum(
            max(item.max_marks, 0.001) for item in awards
        )
        warnings.extend(payload.warnings)
        if confidence < 0.75:
            warnings.append("Low-confidence marking requires careful human review.")

        assessment_id = str(uuid.uuid4())
        result = GradeResponse(
            assessment_id=assessment_id,
            subject_code=self.subject.subject_code,
            question_ref=request.question_ref,
            total_awarded=round(total_awarded, 2),
            total_available=round(total_available, 2),
            confidence=round(confidence, 4),
            status="pending_review",
            rubric_awards=awards,
            symbolic_checks=checks,
            citations=citations,
            warnings=warnings,
            improvement_suggestions=list(
                dict.fromkeys(
                    item.improvement_suggestion for item in awards if item.improvement_suggestion
                )
            ),
            manual_review_required=True,
        )
        now = utcnow()
        self.assessments.create(
            {
                "id": assessment_id,
                "subject_code": self.subject.subject_code,
                "question_ref": request.question_ref,
                "answer_markdown": request.answer_markdown,
                "total_awarded": result.total_awarded,
                "total_available": result.total_available,
                "confidence": result.confidence,
                "status": result.status,
                "result_json": result.model_dump_json(),
                "created_at": now,
                "updated_at": now,
            }
        )
        return result

    def pending_reviews(self) -> list[dict[str, Any]]:
        return [
            {**item, "subject_id": self.subject.id}
            for item in self.assessments.pending(subject_code=self.subject.subject_code)
        ]

    def review(self, assessment_id: str, request: ReviewRequest) -> dict[str, Any]:
        return self.assessments.review(
            assessment_id,
            reviewer=request.reviewer,
            decision=request.decision,
            override_mark=request.override_mark,
            note=request.note,
            subject_code=self.subject.subject_code,
        )
