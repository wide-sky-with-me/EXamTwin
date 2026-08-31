from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, cast

import pymupdf
import pytest
from examtwin.assessment.difficulty_evidence import (
    DifficultyEvidenceService,
    difficulty_input_hash,
    extract_pdf_evidence_pages,
    validate_candidate,
    validate_source_identity,
)
from examtwin.assessment.difficulty_evidence_repository import (
    DifficultyEvidenceRepository,
    difficulty_projection,
)
from examtwin.contracts.difficulty_evidence import (
    DifficultyCandidatePatch,
    DifficultyReviewRequest,
    EvidencePage,
    RawDifficultyCandidate,
)
from pydantic import ValidationError


def _page(text: str, number: int = 2) -> EvidencePage:
    return EvidencePage(
        page_number=number,
        text=text,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def test_a_level_metric_keeps_official_value_and_derives_directional_score() -> None:
    quote = "84% of students scored full marks."
    candidate = RawDifficultyCandidate(
        question_number="01",
        page_number=2,
        quote=quote,
        evidence_level="A",
        metric_name="facility",
        metric_text="84% of students scored full marks",
        metric_value=84,
        metric_scale="percent",
        metric_direction="success",
        metric_comparator="eq",
    )

    result = validate_candidate(
        candidate,
        pages=(_page(quote),),
        valid_question_numbers=frozenset({"1"}),
        source_document_id="report-1",
    )

    assert result.validation_status == "valid"
    assert result.raw.metric_value == 84
    assert result.difficulty_score == pytest.approx(0.16)
    assert result.raw.question_number == "1"


def test_approximate_official_metric_is_preserved_without_precise_projection() -> None:
    quote = "Around 90% of candidates chose the correct answer."
    result = validate_candidate(
        RawDifficultyCandidate(
            question_number="essay:A",
            page_number=2,
            quote=quote,
            evidence_level="A",
            metric_name="facility",
            metric_text="Around 90% of candidates chose the correct answer",
            metric_value=90,
            metric_scale="percent",
            metric_direction="success",
            metric_comparator="approx",
        ),
        pages=(_page(quote),),
        valid_question_numbers=frozenset({"essay:A"}),
        source_document_id="report-1",
    )

    assert result.validation_status == "valid"
    assert result.difficulty_score is None


def test_quantitative_candidate_rejects_value_qualifier_and_direction_mismatch() -> None:
    quote = "Around 90% of candidates chose the correct answer."
    result = validate_candidate(
        RawDifficultyCandidate(
            question_number="essay:A",
            page_number=2,
            quote=quote,
            evidence_level="A",
            metric_name="facility",
            metric_text="Around 90% of candidates chose the correct answer",
            metric_value=80,
            metric_scale="percent",
            metric_direction="difficulty",
            metric_comparator="eq",
        ),
        pages=(_page(quote),),
        valid_question_numbers=frozenset({"essay:A"}),
        source_document_id="report-1",
    )

    assert result.validation_status == "invalid"
    assert "metric_value does not match" in " ".join(result.validation_errors)
    assert "metric_comparator does not match" in " ".join(result.validation_errors)
    assert "difficulty metric_text lacks" in " ".join(result.validation_errors)


def test_multiple_quantitative_observations_require_explicit_aggregation() -> None:
    with pytest.raises(ValueError, match="explicit aggregation policy"):
        difficulty_projection(
            (
                {"evidence_level": "A", "difficulty_score": 0.2},
                {"evidence_level": "A", "difficulty_score": 0.3},
            )
        )


def test_b_level_evidence_remains_qualitative_without_fake_score() -> None:
    quote = "Students found this part challenging."
    result = validate_candidate(
        RawDifficultyCandidate(
            question_number="5",
            page_number=4,
            quote=quote,
            evidence_level="B",
        ),
        pages=(_page(quote, 4),),
        valid_question_numbers=frozenset({"5"}),
        source_document_id="report-1",
    )

    assert result.validation_status == "valid"
    assert result.evidence_type == "qualitative"
    assert result.difficulty_score is None

    with pytest.raises(ValidationError, match="must remain qualitative"):
        RawDifficultyCandidate(
            question_number="5",
            page_number=4,
            quote=quote,
            evidence_level="B",
            metric_name="invented",
            metric_text="challenging",
            metric_value=0.8,
            metric_scale="proportion",
            metric_direction="difficulty",
            metric_comparator="eq",
        )


def test_candidate_validation_rejects_wrong_page_question_and_quote() -> None:
    result = validate_candidate(
        RawDifficultyCandidate(
            question_number="8",
            page_number=3,
            quote="This quote was never present in the supplied page.",
            evidence_level="B",
        ),
        pages=(_page("Canonical report text.", 2),),
        valid_question_numbers=frozenset({"1", "2"}),
        source_document_id="report-1",
    )

    assert result.validation_status == "invalid"
    assert len(result.validation_errors) == 2


def test_source_identity_requires_same_subject_and_strict_question_pair() -> None:
    report = {
        "subject_id": "subject-a",
        "subject_code": "SYNTH",
        "authority_tier": "official",
        "source_role": "assessment_only",
        "source_type": "examiner_report",
        "identity_status": "complete",
        "pair_key": "SYNTH:2026:JUN:U1",
    }
    question = {
        "subject_id": "subject-a",
        "subject_code": "SYNTH",
        "authority_tier": "official",
        "source_role": "assessment_only",
        "source_type": "question_paper",
        "pair_key": "SYNTH:2026:JUN:U1",
    }

    validate_source_identity(
        report,
        subject_id="subject-a",
        subject_code="SYNTH",
        paired_question_document=question,
    )
    with pytest.raises(ValueError, match="active subject"):
        validate_source_identity(
            report,
            subject_id="subject-a",
            subject_code="OTHER",
            paired_question_document=question,
        )


def test_input_hash_changes_with_page_or_package_provenance() -> None:
    values = {
        "subject_id": "subject-a",
        "source_document_id": "report-1",
        "source_checksum": "source-checksum",
        "question_paper_document_id": "question-paper-1",
        "question_paper_checksum": "question-checksum",
        "question_catalog_hash": "question-catalog-hash",
        "pair_key": "SYNTH:2026:JUN:U1",
        "package_digest": "package-v1",
        "extractor_version": "extractor-v1",
        "model_name": "model-a",
        "prompt_digest": "prompt-a",
    }
    first = difficulty_input_hash(**values, pages=(_page("Page one."),))
    second = difficulty_input_hash(**values, pages=(_page("Changed page."),))
    third = difficulty_input_hash(
        **{**values, "package_digest": "package-v2"},
        pages=(_page("Page one."),),
    )

    assert first != second
    assert first != third


class _CorrectionRepository:
    def __init__(self, source: dict[str, Any], run: dict[str, Any]) -> None:
        self.source = source
        self.run = run
        self.appended: dict[str, Any] | None = None

    def require_run(self, subject_id: str, run_id: str) -> dict[str, Any]:
        assert (subject_id, run_id) == ("subject-synthetic", "run-1")
        return self.run

    def require_source_document(self, document_id: str) -> dict[str, Any]:
        assert document_id == "report-1"
        return self.source

    def append_review(self, **values: Any) -> dict[str, Any]:
        self.appended = values
        return self.run


def test_candidate_correction_is_revalidated_against_frozen_source(tmp_path: Path) -> None:
    source_path = tmp_path / "report.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Students found Question 3 challenging.")
    document.save(source_path)
    document.close()
    checksum = hashlib.sha256(source_path.read_bytes()).hexdigest()
    candidate = {
        "id": "candidate-1",
        "run_id": "run-1",
        "question_number": "3",
        "page_number": 1,
        "quote": "incorrect original quote",
        "evidence_level": "B",
        "metric_name": None,
        "metric_text": None,
        "metric_value": None,
        "metric_scale": None,
        "metric_direction": None,
        "model_confidence": None,
        "review_replacement": {},
    }
    run = {
        "id": "run-1",
        "source_document_id": "report-1",
        "source_checksum": checksum,
        "question_catalog_json": '["3"]',
        "candidates": [candidate],
    }
    repository = _CorrectionRepository(
        {
            "id": "report-1",
            "path": str(source_path),
            "checksum": checksum,
            "status": "discovered",
        },
        run,
    )
    service = DifficultyEvidenceService(cast(DifficultyEvidenceRepository, repository))

    service.review_candidate(
        subject_id="subject-synthetic",
        run_id="run-1",
        candidate_id="candidate-1",
        review=DifficultyReviewRequest(
            decision="accepted",
            expected_candidate_fingerprint="f" * 64,
            replacement=DifficultyCandidatePatch(quote="Students found Question 3 challenging."),
        ),
        reviewer="local:test",
    )

    assert repository.appended is not None
    replacement = repository.appended["replacement"]
    assert replacement["validation_status"] == "valid"
    assert replacement["difficulty_score"] is None


@pytest.mark.parametrize(
    "relative_path, expected_text",
    [
        (
            "data/牛津AQA/数学/5.AQA-alevel数学-历年真题/AS/2024/补充/er-202401-math-up1.pdf",
            "Over 90% of students answered this part correctly.",
        ),
        (
            "data/牛津AQA/经济/AQA alevel 经济 真题（18-23年）/"
            "AQA Alevel经济2023真题/辅助资料/er-202301-economics-u1.pdf",
            "Nine of the questions had a facility of 65% or more.",
        ),
    ],
)
def test_real_examiner_reports_preserve_page_bound_verbatim_text(
    relative_path: str,
    expected_text: str,
) -> None:
    root = Path(__file__).resolve().parents[2]
    pages = extract_pdf_evidence_pages(root / relative_path)

    assert any(expected_text in page.text for page in pages)
