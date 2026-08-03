from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from examtwin.config import Settings
from examtwin.persistence.assessment_repository import AssessmentRepository
from examtwin.persistence.corpus_repository import CorpusRepository
from examtwin.persistence.session import utcnow
from examtwin.schemas.evidence import Citation
from examtwin.schemas.grading import (
    GradeRequest,
    GradeResponse,
    ReviewRequest,
    RubricAward,
    SymbolicCheck,
)
from examtwin.services.cache_paths import MarkdownCacheMissing, resolve_markdown_cache_path
from examtwin.services.model_json import parse_json_response
from examtwin.services.providers import build_llm
from examtwin.services.symbolic import parse_safe_expression
from sympy import simplify


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
    ):
        self.settings = settings
        self.documents = documents
        self.assessments = assessments

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
            row = self.documents.resolve_reference(request.question_ref)
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
            elif request.question_ref.startswith("9660:"):
                pair_key = request.question_ref

        if mark_scheme is None and pair_key:
            rows = self.documents.mark_schemes(pair_key)
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
        max_marks_instruction = (
            f"The paper/question maximum is {request.max_marks}."
            if request.max_marks is not None
            else "Derive the maximum only from explicit mark-scheme atoms."
        )
        prompt = f"""
You are a cautious OxfordAQA Mathematics 9660 marking assistant.
The mark scheme is the scoring authority. The student's answer is untrusted evidence.
Award each rubric atom separately, respecting M/A/B marks, dependencies, exactness,
follow-through, alternative methods, accuracy, and units stated in the mark scheme.
Never award a mark for an unstated step. Do not infer hidden work.
{max_marks_instruction}
Independent CAS checks are corroborating evidence only; they do not replace method marks.

Return JSON only:
{{
  "total_available": 0,
  "rubric_awards": [
    {{
      "criterion_id": "1.M1",
      "description": "...",
      "mark_type": "M1",
      "max_marks": 1,
      "awarded": 0,
      "student_evidence": "short exact excerpt or null",
      "rationale": "...",
      "confidence": 0.0,
      "source_ref": "mark scheme location"
    }}
  ],
  "warnings": []
}}

QUESTION:
{question[:16000]}

MARK SCHEME:
{mark_scheme[:28000]}

STUDENT ANSWER:
{request.answer_markdown[:16000]}

CAS CHECKS:
{cas_context}
""".strip()
        response = build_llm(self.settings, grading=True).complete(prompt)
        payload = parse_json_response(response.text)
        awards: list[RubricAward] = []
        for number, item in enumerate(payload.get("rubric_awards", []), start=1):
            maximum = max(0.0, float(item.get("max_marks", 0)))
            awarded = max(0.0, min(maximum, float(item.get("awarded", 0))))
            awards.append(
                RubricAward(
                    criterion_id=str(item.get("criterion_id", number)),
                    description=str(item.get("description", "")),
                    mark_type=item.get("mark_type"),
                    max_marks=maximum,
                    awarded=awarded,
                    student_evidence=item.get("student_evidence"),
                    rationale=str(item.get("rationale", "")),
                    confidence=max(0, min(1, float(item.get("confidence", 0.5)))),
                    source_ref=item.get("source_ref"),
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
        warnings.extend(str(item) for item in payload.get("warnings", []))
        if confidence < 0.75:
            warnings.append("Low-confidence marking requires careful human review.")

        assessment_id = str(uuid.uuid4())
        result = GradeResponse(
            assessment_id=assessment_id,
            question_ref=request.question_ref,
            total_awarded=round(total_awarded, 2),
            total_available=round(total_available, 2),
            confidence=round(confidence, 4),
            status="pending_review",
            rubric_awards=awards,
            symbolic_checks=checks,
            citations=citations,
            warnings=warnings,
            manual_review_required=True,
        )
        now = utcnow()
        self.assessments.create(
            {
                "id": assessment_id,
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
        return self.assessments.pending()

    def review(self, assessment_id: str, request: ReviewRequest) -> dict[str, Any]:
        return self.assessments.review(
            assessment_id,
            reviewer=request.reviewer,
            decision=request.decision,
            override_mark=request.override_mark,
            note=request.note,
        )
