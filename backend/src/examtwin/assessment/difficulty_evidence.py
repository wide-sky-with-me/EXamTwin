from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pymupdf

from examtwin.assessment.difficulty_evidence_repository import (
    DifficultyEvidenceRepository,
)
from examtwin.contracts.difficulty_evidence import (
    DifficultyReviewRequest,
    EvidencePage,
    RawDifficultyCandidate,
    RawDifficultyCandidateBatch,
    RawQuestionCatalog,
)
from examtwin.platform.agent_runtime.structured import (
    StructuredModelPort,
    StructuredTask,
    StructuredTaskRunner,
)
from examtwin.platform.database.session import utcnow
from examtwin.subjects.public import SubjectContext

EXTRACTOR_VERSION = "examiner-evidence-v2"
PROMPT_VERSION = "examiner-evidence-structured-v2"


@dataclass(frozen=True)
class ValidatedDifficultyCandidate:
    raw: RawDifficultyCandidate
    evidence_type: str
    difficulty_score: float | None
    quote_hash: str
    block_hash: str
    source_ref: str
    validation_errors: tuple[str, ...]

    @property
    def validation_status(self) -> str:
        return "valid" if not self.validation_errors else "invalid"


def normalized_source_text(value: str) -> str:
    return " ".join(value.split())


def source_file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def extract_pdf_evidence_pages(path: Path) -> tuple[EvidencePage, ...]:
    with pymupdf.open(path) as document:
        pages = []
        for page_index in range(document.page_count):
            page_number = page_index + 1
            page = document.load_page(page_index)
            text = normalized_source_text(cast(str, page.get_text("text")))
            if not text:
                continue
            pages.append(
                EvidencePage(
                    page_number=page_number,
                    text=text,
                    content_hash=hashlib.sha256(text.encode()).hexdigest(),
                )
            )
    if not pages:
        raise ValueError("examiner report contains no extractable page text")
    return tuple(pages)


def validate_source_identity(
    document: Mapping[str, Any],
    *,
    subject_id: str,
    subject_code: str,
    paired_question_document: Mapping[str, Any] | None,
) -> None:
    if document.get("subject_id") != subject_id:
        raise ValueError("examiner report belongs to a different subject workspace")
    if document.get("authority_tier") != "official":
        raise ValueError("difficulty evidence requires an official Examiner Report")
    if document.get("source_role") != "assessment_only":
        raise ValueError("examiner report is not assigned for assessment evidence")
    if document.get("subject_code") != subject_code:
        raise ValueError("examiner report subject_code does not match the active subject")
    if document.get("source_type") != "examiner_report":
        raise ValueError("difficulty evidence source must be an examiner report")
    if document.get("identity_status") != "complete":
        raise ValueError("examiner report requires complete exam identity")
    pair_key = str(document.get("pair_key") or "")
    if not pair_key:
        raise ValueError("examiner report requires an exact pair_key")
    if paired_question_document is None:
        raise ValueError("examiner report requires a strictly paired question paper")
    if paired_question_document.get("source_type") != "question_paper":
        raise ValueError("paired source must be a question paper")
    if paired_question_document.get("subject_id") != subject_id:
        raise ValueError("paired question paper belongs to a different subject workspace")
    if paired_question_document.get("subject_code") != subject_code:
        raise ValueError("paired question paper belongs to a different subject")
    if paired_question_document.get("authority_tier") != "official":
        raise ValueError("paired question paper requires official authority")
    if paired_question_document.get("source_role") != "assessment_only":
        raise ValueError("paired question paper is not assigned for assessment evidence")
    if paired_question_document.get("pair_key") != pair_key:
        raise ValueError("examiner report and question paper pair_key do not match")


def difficulty_input_hash(
    *,
    subject_id: str,
    source_document_id: str,
    source_checksum: str,
    question_paper_document_id: str,
    question_paper_checksum: str,
    question_catalog_hash: str,
    pair_key: str,
    package_digest: str,
    extractor_version: str,
    model_name: str,
    prompt_digest: str,
    pages: Sequence[EvidencePage],
) -> str:
    payload = {
        "subject_id": subject_id,
        "source_document_id": source_document_id,
        "source_checksum": source_checksum,
        "question_paper_document_id": question_paper_document_id,
        "question_paper_checksum": question_paper_checksum,
        "question_catalog_hash": question_catalog_hash,
        "pair_key": pair_key,
        "package_digest": package_digest,
        "extractor_version": extractor_version,
        "model_name": model_name,
        "prompt_digest": prompt_digest,
        "pages": [
            {"page_number": page.page_number, "content_hash": page.content_hash} for page in pages
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _metric_text_errors(candidate: RawDifficultyCandidate) -> tuple[str, ...]:
    if candidate.evidence_level != "A" or candidate.metric_text is None:
        return ()
    text = candidate.metric_text.casefold()
    values = re.findall(r"(?<![0-9.])([0-9]+(?:\.[0-9]+)?)(?![0-9.])", text)
    errors: list[str] = []
    if len(values) != 1 or candidate.metric_value is None:
        errors.append("metric_text must contain exactly one official numeric value")
    elif abs(float(values[0]) - candidate.metric_value) > 1e-9:
        errors.append("metric_value does not match the numeric value in metric_text")
    if candidate.metric_scale == "percent" and "%" not in text:
        errors.append("percent metric_text must contain a percent sign")
    if candidate.metric_scale == "proportion" and "%" in text:
        errors.append("proportion metric_text cannot contain a percent sign")
    comparator = "eq"
    approximate_tokens = ("approximately", "around", "about", "nearly", "close to", "~")
    if any(token in text for token in approximate_tokens):
        comparator = "approx"
    elif any(token in text for token in ("at least", "or more", ">=")):
        comparator = "gte"
    elif any(token in text for token in ("more than", "over ", ">")):
        comparator = "gt"
    elif any(token in text for token in ("at most", "or less", "<=")):
        comparator = "lte"
    elif any(token in text for token in ("less than", "under ", "<")):
        comparator = "lt"
    if candidate.metric_comparator != comparator:
        errors.append("metric_comparator does not match the qualifier in metric_text")
    success_tokens = ("correct", "full mark", "facility", "success", "scored")
    difficulty_tokens = ("incorrect", "failed", "unable", "error", "difficulty")
    has_success = any(token in text for token in success_tokens)
    has_difficulty = any(token in text for token in difficulty_tokens)
    if candidate.metric_direction == "success" and not has_success:
        errors.append("success metric_text lacks an explicit success marker")
    if candidate.metric_direction == "difficulty" and not has_difficulty:
        errors.append("difficulty metric_text lacks an explicit difficulty marker")
    return tuple(errors)


def _difficulty_score(candidate: RawDifficultyCandidate) -> float | None:
    if candidate.evidence_level == "B" or candidate.metric_comparator != "eq":
        return None
    if candidate.metric_value is None or candidate.metric_scale is None:
        return None
    proportion = (
        candidate.metric_value / 100
        if candidate.metric_scale == "percent"
        else candidate.metric_value
    )
    return round(1 - proportion if candidate.metric_direction == "success" else proportion, 6)


def validate_candidate(
    candidate: RawDifficultyCandidate,
    *,
    pages: Sequence[EvidencePage],
    valid_question_numbers: frozenset[str],
    source_document_id: str,
) -> ValidatedDifficultyCandidate:
    errors: list[str] = []
    page = next(
        (item for item in pages if item.page_number == candidate.page_number),
        None,
    )
    if candidate.question_number not in valid_question_numbers:
        errors.append("question_number is not present in the paired question paper")
    if page is None:
        errors.append("page_number is not present in the examiner report")
    elif candidate.quote not in page.text:
        errors.append("quote is not verbatim text from the declared source page")
    if candidate.metric_text is not None and candidate.metric_text not in candidate.quote:
        errors.append("official metric_text is not verbatim text from the quote")
    errors.extend(_metric_text_errors(candidate))

    quote_hash = hashlib.sha256(candidate.quote.encode()).hexdigest()
    block_hash = page.content_hash if page is not None else hashlib.sha256(b"").hexdigest()
    source_ref = (
        f"document:{source_document_id}:page:{candidate.page_number}:quote:{quote_hash[:12]}"
    )
    return ValidatedDifficultyCandidate(
        raw=candidate,
        evidence_type="quantitative" if candidate.evidence_level == "A" else "qualitative",
        difficulty_score=_difficulty_score(candidate),
        quote_hash=quote_hash,
        block_hash=block_hash,
        source_ref=source_ref,
        validation_errors=tuple(errors),
    )


def candidate_storage_values(
    validated: ValidatedDifficultyCandidate,
    *,
    candidate_id: str,
    run_id: str,
    subject_id: str,
    subject_code: str,
    source_document_id: str,
    source_checksum: str,
    pair_key: str,
    unit_code: str | None,
    created_at: Any,
) -> dict[str, Any]:
    raw = validated.raw
    return {
        "id": candidate_id,
        "run_id": run_id,
        "subject_id": subject_id,
        "subject_code": subject_code,
        "source_document_id": source_document_id,
        "source_checksum": source_checksum,
        "pair_key": pair_key,
        "unit_code": unit_code,
        "question_number": raw.question_number,
        "page_number": raw.page_number,
        "evidence_level": raw.evidence_level,
        "evidence_type": validated.evidence_type,
        "metric_name": raw.metric_name,
        "metric_text": raw.metric_text,
        "metric_value": raw.metric_value,
        "metric_scale": raw.metric_scale,
        "metric_direction": raw.metric_direction,
        "metric_comparator": raw.metric_comparator,
        "difficulty_score": validated.difficulty_score,
        "quote": raw.quote,
        "quote_hash": validated.quote_hash,
        "block_hash": validated.block_hash,
        "source_ref": validated.source_ref,
        "model_confidence": raw.model_confidence,
        "validation_status": validated.validation_status,
        "validation_errors_json": json.dumps(validated.validation_errors),
        "created_at": created_at,
    }


EXTRACTION_SYSTEM_PROMPT = """
Extract candidate question-level difficulty evidence from an official Examiner Report.
Use only exact statements from the supplied page text and only canonical question numbers
from the supplied question catalog. Return A-level evidence only when the report states an
explicit quantitative metric. Preserve exact metric text that includes the number, any qualifier
(approximately/around/about/over/under/at least/at most), and the words establishing whether
it measures success or difficulty. Set metric_comparator to match that qualifier; use eq only when
the report states an exact value. Return B-level evidence for official qualitative
statements and leave every metric field null. Never infer a score, map a knowledge code,
combine observations, or guess a question number. Every quote must be an exact substring of
one declared page.
""".strip()


def extraction_prompt_digest() -> str:
    return hashlib.sha256(EXTRACTION_SYSTEM_PROMPT.encode()).hexdigest()


QUESTION_CATALOG_SYSTEM_PROMPT = """
Extract canonical question identifiers from this official Question Paper page. Return only
questions whose printed identifier is visible on this page. For each identifier, include the
page number and an exact short marker_quote copied from the page that contains the identifier.
Identifiers may be numeric, alphabetic, nested, or punctuation-delimited; preserve the printed
canonical form. Do not infer missing identifiers.
""".strip()


def extract_verified_question_catalog(
    model: StructuredModelPort,
    *,
    pages: Sequence[EvidencePage],
    timeout: float,
) -> frozenset[str]:
    runner = StructuredTaskRunner(model)
    by_page = {page.page_number: page for page in pages}
    numbers: set[str] = set()
    for page in pages:
        payload = runner.run(
            StructuredTask(
                system_prompt=QUESTION_CATALOG_SYSTEM_PROMPT,
                user_content=(
                    f"PAGE NUMBER: {page.page_number}\n"
                    f"PAGE CONTENT HASH: {page.content_hash}\n\n"
                    f"PAGE TEXT:\n{page.text}"
                ),
            ),
            RawQuestionCatalog,
            timeout=timeout,
        )
        for entry in payload.entries:
            source_page = by_page.get(entry.page_number)
            marker = normalized_source_text(entry.marker_quote)
            if (
                entry.page_number != page.page_number
                or source_page is None
                or marker not in source_page.text
            ):
                raise ValueError("question catalog marker is not verbatim source text")
            numbers.add(RawDifficultyCandidate.canonicalize_question_number(entry.question_number))
    if not numbers:
        raise ValueError("paired question paper produced an empty verified question catalog")
    return frozenset(numbers)


def extract_structured_candidates(
    model: StructuredModelPort,
    *,
    pages: Sequence[EvidencePage],
    question_numbers: frozenset[str],
    timeout: float,
) -> tuple[RawDifficultyCandidate, ...]:
    candidates: list[RawDifficultyCandidate] = []
    runner = StructuredTaskRunner(model)
    catalog = ", ".join(sorted(question_numbers, key=lambda value: (len(value), value)))
    for page in pages:
        payload = runner.run(
            StructuredTask(
                system_prompt=EXTRACTION_SYSTEM_PROMPT,
                user_content=(
                    f"CANONICAL QUESTION NUMBERS: {catalog}\n"
                    f"PAGE NUMBER: {page.page_number}\n"
                    f"PAGE CONTENT HASH: {page.content_hash}\n\n"
                    f"PAGE TEXT:\n{page.text}"
                ),
            ),
            RawDifficultyCandidateBatch,
            timeout=timeout,
        )
        candidates.extend(payload.candidates)
    return tuple(candidates)


class DifficultyEvidenceService:
    def __init__(
        self,
        repository: DifficultyEvidenceRepository,
        *,
        model: StructuredModelPort | None = None,
        model_name: str = "",
        timeout: float = 120.0,
    ) -> None:
        self.repository = repository
        self.model = model
        self.model_name = model_name
        self.timeout = timeout

    def create_from_source(
        self,
        *,
        subject: SubjectContext,
        source_document_id: str,
    ) -> dict[str, Any]:
        if self.model is None:
            raise RuntimeError("difficulty evidence extraction model is unavailable")
        report = self.repository.require_source_document(source_document_id)
        if report["authority_tier"] != "official":
            raise ValueError("difficulty evidence requires an official Examiner Report")
        question_paper = self.repository.require_paired_question_paper(
            subject_code=subject.subject_code,
            pair_key=str(report.get("pair_key") or ""),
        )
        validate_source_identity(
            report,
            subject_id=subject.id,
            subject_code=subject.subject_code,
            paired_question_document=question_paper,
        )
        report_path = Path(str(report["path"]))
        question_path = Path(str(question_paper["path"]))
        for source, path in ((report, report_path), (question_paper, question_path)):
            if not path.is_file() or source_file_checksum(path) != source["checksum"]:
                raise ValueError("difficulty evidence source bytes do not match catalog checksum")
        report_pages = extract_pdf_evidence_pages(report_path)
        question_pages = extract_pdf_evidence_pages(question_path)
        question_numbers = extract_verified_question_catalog(
            self.model,
            pages=question_pages,
            timeout=self.timeout,
        )
        candidates = extract_structured_candidates(
            self.model,
            pages=report_pages,
            question_numbers=question_numbers,
            timeout=self.timeout,
        )
        return self._persist_review_run(
            subject=subject,
            report=report,
            question_paper=question_paper,
            pages=report_pages,
            question_numbers=question_numbers,
            raw_candidates=candidates,
            model_name=self.model_name,
        )

    def _persist_review_run(
        self,
        *,
        subject: SubjectContext,
        report: Mapping[str, Any],
        question_paper: Mapping[str, Any],
        pages: Sequence[EvidencePage],
        question_numbers: frozenset[str],
        raw_candidates: Sequence[RawDifficultyCandidate],
        model_name: str,
        prompt_digest: str | None = None,
    ) -> dict[str, Any]:
        if report.get("status") == "deleted" or question_paper.get("status") == "deleted":
            raise ValueError("archived sources must be rediscovered before extraction")
        if report.get("authority_tier") != "official":
            raise ValueError("difficulty evidence requires official source authority")
        validate_source_identity(
            report,
            subject_id=subject.id,
            subject_code=subject.subject_code,
            paired_question_document=question_paper,
        )
        source_checksum = str(report.get("checksum") or "")
        question_checksum = str(question_paper.get("checksum") or "")
        if not source_checksum or not question_checksum:
            raise ValueError("difficulty evidence requires frozen source checksums")
        if not question_numbers:
            raise ValueError("paired question paper produced an empty question catalog")
        question_catalog = sorted(question_numbers, key=lambda value: (len(value), value))
        question_catalog_json = json.dumps(question_catalog, separators=(",", ":"))
        question_catalog_hash = hashlib.sha256(question_catalog_json.encode()).hexdigest()
        resolved_prompt_digest = prompt_digest or extraction_prompt_digest()
        input_hash = difficulty_input_hash(
            subject_id=subject.id,
            source_document_id=str(report["id"]),
            source_checksum=source_checksum,
            question_paper_document_id=str(question_paper["id"]),
            question_paper_checksum=question_checksum,
            question_catalog_hash=question_catalog_hash,
            pair_key=str(report["pair_key"]),
            package_digest=subject.package.digest,
            extractor_version=EXTRACTOR_VERSION,
            model_name=model_name,
            prompt_digest=resolved_prompt_digest,
            pages=pages,
        )
        run_id = uuid.uuid5(uuid.NAMESPACE_URL, f"examtwin:difficulty:{input_hash}").hex
        now = utcnow()
        validated = [
            validate_candidate(
                candidate,
                pages=pages,
                valid_question_numbers=question_numbers,
                source_document_id=str(report["id"]),
            )
            for candidate in raw_candidates
        ]
        candidate_values = []
        for ordinal, item in enumerate(validated, start=1):
            payload = item.raw.model_dump(mode="json")
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            candidate_id = uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"examtwin:difficulty:{run_id}:{ordinal}:{encoded}",
            ).hex
            candidate_values.append(
                candidate_storage_values(
                    item,
                    candidate_id=candidate_id,
                    run_id=run_id,
                    subject_id=subject.id,
                    subject_code=subject.subject_code,
                    source_document_id=str(report["id"]),
                    source_checksum=source_checksum,
                    pair_key=str(report["pair_key"]),
                    unit_code=str(report.get("unit_code") or "") or None,
                    created_at=now,
                )
            )
        return self.repository.create_or_reuse_run(
            {
                "id": run_id,
                "subject_id": subject.id,
                "subject_code": subject.subject_code,
                "source_document_id": str(report["id"]),
                "source_checksum": source_checksum,
                "question_paper_document_id": str(question_paper["id"]),
                "question_paper_checksum": question_checksum,
                "question_catalog_json": question_catalog_json,
                "question_catalog_hash": question_catalog_hash,
                "pair_key": str(report["pair_key"]),
                "input_hash": input_hash,
                "package_digest": subject.package.digest,
                "extractor_version": EXTRACTOR_VERSION,
                "model_name": model_name,
                "prompt_digest": resolved_prompt_digest,
                "status": "review_ready",
                "candidate_count": len(candidate_values),
                "error": None,
                "created_at": now,
                "updated_at": now,
                "completed_at": now,
                "published_at": None,
            },
            candidate_values,
        )

    def list_runs(self, subject_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        return self.repository.list_runs(subject_id, limit=limit)

    def require_run(self, subject_id: str, run_id: str) -> dict[str, Any]:
        return self.repository.require_run(subject_id, run_id)

    def review_candidate(
        self,
        *,
        subject_id: str,
        run_id: str,
        candidate_id: str,
        review: DifficultyReviewRequest,
        reviewer: str,
    ) -> dict[str, Any]:
        replacement = (
            review.replacement.model_dump(exclude_unset=True)
            if review.replacement is not None
            else {}
        )
        if replacement:
            run = self.repository.require_run(subject_id, run_id)
            candidate = next(
                (item for item in run["candidates"] if item["id"] == candidate_id),
                None,
            )
            if candidate is None:
                raise LookupError("difficulty evidence candidate not found")
            effective = {**candidate, **candidate["review_replacement"], **replacement}
            raw = RawDifficultyCandidate.model_validate(
                {
                    key: effective.get(key)
                    for key in (
                        "question_number",
                        "page_number",
                        "quote",
                        "evidence_level",
                        "metric_name",
                        "metric_text",
                        "metric_value",
                        "metric_scale",
                        "metric_direction",
                        "metric_comparator",
                        "model_confidence",
                    )
                }
            )
            source = self.repository.require_source_document(run["source_document_id"])
            if source["status"] == "deleted" or source["checksum"] != run["source_checksum"]:
                raise ValueError("candidate source changed before correction review")
            pages = extract_pdf_evidence_pages(Path(str(source["path"])))
            validated = validate_candidate(
                raw,
                pages=pages,
                valid_question_numbers=frozenset(json.loads(run["question_catalog_json"])),
                source_document_id=run["source_document_id"],
            )
            replacement = {
                **raw.model_dump(mode="json"),
                "evidence_type": validated.evidence_type,
                "difficulty_score": validated.difficulty_score,
                "quote_hash": validated.quote_hash,
                "block_hash": validated.block_hash,
                "source_ref": validated.source_ref,
                "validation_status": validated.validation_status,
                "validation_errors_json": json.dumps(validated.validation_errors),
            }
        return self.repository.append_review(
            subject_id=subject_id,
            run_id=run_id,
            candidate_id=candidate_id,
            decision=review.decision,
            reviewer=reviewer,
            notes=review.notes,
            replacement=replacement,
            expected_fingerprint=review.expected_candidate_fingerprint,
        )

    def publish_run(
        self,
        *,
        subject_id: str,
        run_id: str,
        expected_fingerprint: str,
        reviewer: str,
    ) -> dict[str, Any]:
        run = self.repository.require_run(subject_id, run_id)
        if run["status"] != "published":
            for document_id, expected_checksum in (
                (run["source_document_id"], run["source_checksum"]),
                (run["question_paper_document_id"], run["question_paper_checksum"]),
            ):
                source = self.repository.require_source_document(document_id)
                path = Path(str(source["path"]))
                if not path.is_file():
                    raise ValueError("difficulty evidence source file is not readable")
                if source_file_checksum(path) != expected_checksum:
                    raise ValueError("difficulty evidence source bytes changed after extraction")
        return self.repository.publish_run(
            subject_id=subject_id,
            run_id=run_id,
            expected_fingerprint=expected_fingerprint,
            reviewer=reviewer,
        )
