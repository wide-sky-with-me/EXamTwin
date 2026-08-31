from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from examtwin.knowledge.public import difficulty_label
from examtwin.platform.database.models import (
    DifficultyEvidenceCandidateModel,
    DifficultyEvidenceReviewModel,
    DifficultyEvidenceRunModel,
    QuestionDifficultyModel,
    SourceDocumentModel,
)
from examtwin.platform.database.session import utcnow


def _row_dict(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def run_fingerprint(run: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]) -> str:
    payload = {
        "run_id": run["id"],
        "input_hash": run["input_hash"],
        "status": run["status"],
        "candidates": [
            {
                "id": item["id"],
                "fingerprint": item["candidate_fingerprint"],
                "decision": item.get("review_decision"),
            }
            for item in candidates
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def candidate_fingerprint(candidate: Mapping[str, Any], replacement: Mapping[str, Any]) -> str:
    editable = {
        key: replacement.get(key, candidate.get(key))
        for key in (
            "question_number",
            "page_number",
            "evidence_level",
            "evidence_type",
            "metric_name",
            "metric_text",
            "metric_value",
            "metric_scale",
            "metric_direction",
            "metric_comparator",
            "difficulty_score",
            "quote",
            "quote_hash",
            "block_hash",
            "source_ref",
            "validation_status",
            "validation_errors_json",
        )
    }
    encoded = json.dumps(editable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def difficulty_projection(evidence: Sequence[Mapping[str, Any]]) -> tuple[float | None, str]:
    quantitative = [item for item in evidence if item["evidence_level"] == "A"]
    if len(quantitative) > 1:
        raise ValueError("multiple A-level observations require an explicit aggregation policy")
    score = None
    if quantitative and quantitative[0].get("difficulty_score") is not None:
        score = float(quantitative[0]["difficulty_score"])
    level = "A" if quantitative else "B"
    return score, level


class DifficultyEvidenceRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def create_or_reuse_run(
        self,
        run_values: Mapping[str, Any],
        candidate_values: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        with self.sessions.begin() as session:
            statement = (
                insert(DifficultyEvidenceRunModel)
                .values(**dict(run_values))
                .on_conflict_do_nothing(index_elements=["subject_id", "input_hash"])
            )
            inserted_id = session.scalar(statement.returning(DifficultyEvidenceRunModel.id))
            run = session.scalar(
                select(DifficultyEvidenceRunModel).where(
                    DifficultyEvidenceRunModel.subject_id == run_values["subject_id"],
                    DifficultyEvidenceRunModel.input_hash == run_values["input_hash"],
                )
            )
            if run is None:
                raise RuntimeError("difficulty evidence run could not be created")
            if inserted_id is not None:
                session.add_all(
                    DifficultyEvidenceCandidateModel(**dict(values)) for values in candidate_values
                )
        return self.require_run(str(run_values["subject_id"]), str(run.id))

    def require_run(self, subject_id: str, run_id: str) -> dict[str, Any]:
        with self.sessions() as session:
            run = session.scalar(
                select(DifficultyEvidenceRunModel).where(
                    DifficultyEvidenceRunModel.id == run_id,
                    DifficultyEvidenceRunModel.subject_id == subject_id,
                )
            )
            if run is None:
                raise LookupError("difficulty evidence run not found")
            result = _row_dict(run)
            result["candidates"] = self._candidate_views(session, run_id)
            result["run_fingerprint"] = run_fingerprint(result, result["candidates"])
            return result

    def require_paired_question_paper(
        self,
        *,
        subject_code: str,
        pair_key: str,
    ) -> dict[str, Any]:
        with self.sessions() as session:
            rows = list(
                session.scalars(
                    select(SourceDocumentModel).where(
                        SourceDocumentModel.subject_code == subject_code,
                        SourceDocumentModel.pair_key == pair_key,
                        SourceDocumentModel.source_type == "question_paper",
                        SourceDocumentModel.status != "deleted",
                    )
                )
            )
            if len(rows) != 1:
                raise ValueError(
                    "examiner report requires exactly one active paired question paper"
                )
            return _row_dict(rows[0])

    def require_source_document(self, document_id: str) -> dict[str, Any]:
        with self.sessions() as session:
            document = session.get(SourceDocumentModel, document_id)
            if document is None:
                raise LookupError("difficulty evidence source is no longer available")
            return _row_dict(document)

    def list_runs(self, subject_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        with self.sessions() as session:
            rows = list(
                session.scalars(
                    select(DifficultyEvidenceRunModel)
                    .where(DifficultyEvidenceRunModel.subject_id == subject_id)
                    .order_by(DifficultyEvidenceRunModel.created_at.desc())
                    .limit(limit)
                )
            )
            return [_row_dict(row) for row in rows]

    def append_review(
        self,
        *,
        subject_id: str,
        run_id: str,
        candidate_id: str,
        decision: str,
        reviewer: str,
        notes: str | None,
        replacement: Mapping[str, Any],
        expected_fingerprint: str,
    ) -> dict[str, Any]:
        if decision not in {"accepted", "rejected"}:
            raise ValueError("review decision must be accepted or rejected")
        if decision == "rejected" and not (notes or "").strip():
            raise ValueError("rejected difficulty evidence requires review notes")
        now = utcnow()
        with self.sessions.begin() as session:
            run = session.scalar(
                select(DifficultyEvidenceRunModel)
                .where(
                    DifficultyEvidenceRunModel.id == run_id,
                    DifficultyEvidenceRunModel.subject_id == subject_id,
                )
                .with_for_update()
            )
            if run is None:
                raise LookupError("difficulty evidence run not found")
            if run.status == "published":
                raise ValueError("published difficulty evidence is immutable")
            candidate = session.scalar(
                select(DifficultyEvidenceCandidateModel)
                .where(
                    DifficultyEvidenceCandidateModel.id == candidate_id,
                    DifficultyEvidenceCandidateModel.run_id == run_id,
                )
                .with_for_update()
            )
            if candidate is None:
                raise LookupError("difficulty evidence candidate not found")
            latest = self._latest_review(session, candidate_id)
            latest_replacement = json.loads(latest.replacement_json) if latest is not None else {}
            current = candidate_fingerprint(_row_dict(candidate), latest_replacement)
            if current != expected_fingerprint:
                raise ValueError("difficulty evidence candidate fingerprint is stale")
            effective_replacement = {**latest_replacement, **dict(replacement)}
            if decision == "accepted":
                status = effective_replacement.get("validation_status", candidate.validation_status)
                if status != "valid":
                    raise ValueError("invalid difficulty evidence cannot be accepted")
            sequence = 1 if latest is None else latest.sequence + 1
            session.add(
                DifficultyEvidenceReviewModel(
                    id=uuid.uuid4().hex,
                    candidate_id=candidate_id,
                    sequence=sequence,
                    decision=decision,
                    replacement_json=json.dumps(
                        effective_replacement,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    reviewer=reviewer.strip(),
                    notes=(notes or "").strip() or None,
                    created_at=now,
                )
            )
            run.updated_at = now
        return self.require_run(subject_id, run_id)

    def publish_run(
        self,
        *,
        subject_id: str,
        run_id: str,
        expected_fingerprint: str,
        reviewer: str,
    ) -> dict[str, Any]:
        now = utcnow()
        with self.sessions.begin() as session:
            run = session.scalar(
                select(DifficultyEvidenceRunModel)
                .where(
                    DifficultyEvidenceRunModel.id == run_id,
                    DifficultyEvidenceRunModel.subject_id == subject_id,
                )
                .with_for_update()
            )
            if run is None:
                raise LookupError("difficulty evidence run not found")
            if run.status == "published":
                return _row_dict(run)
            current_views = self._candidate_views(session, run_id)
            if run_fingerprint(_row_dict(run), current_views) != expected_fingerprint:
                raise ValueError("difficulty evidence run fingerprint is stale")
            session.execute(
                select(func.pg_advisory_xact_lock(func.hashtext(run.source_document_id)))
            )
            self._validate_frozen_sources(session, run)
            candidates = list(
                session.scalars(
                    select(DifficultyEvidenceCandidateModel)
                    .where(DifficultyEvidenceCandidateModel.run_id == run_id)
                    .order_by(DifficultyEvidenceCandidateModel.id)
                    .with_for_update()
                )
            )
            accepted: list[dict[str, Any]] = []
            for candidate in candidates:
                review = self._latest_review(session, candidate.id)
                if review is None:
                    raise ValueError("all difficulty evidence candidates must be reviewed")
                if review.decision == "accepted":
                    effective = {**_row_dict(candidate), **json.loads(review.replacement_json)}
                    if effective["validation_status"] != "valid":
                        raise ValueError("invalid difficulty evidence cannot be published")
                    accepted.append(effective)
            if not accepted:
                raise ValueError("at least one accepted difficulty evidence candidate is required")

            session.execute(
                delete(QuestionDifficultyModel).where(
                    QuestionDifficultyModel.source_document_id == run.source_document_id
                )
            )
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for candidate in accepted:
                grouped[str(candidate["question_number"])].append(candidate)
            for question_number, evidence in grouped.items():
                score, level = difficulty_projection(evidence)
                session.add(
                    QuestionDifficultyModel(
                        source_document_id=run.source_document_id,
                        question_ref=f"{run.pair_key}:Q{question_number}",
                        pair_key=run.pair_key,
                        question_number=question_number,
                        difficulty_score=score,
                        difficulty_label=difficulty_label(score) if score is not None else None,
                        confidence=None,
                        evidence_level=level,
                        knowledge_codes_json="[]",
                        evidence_json=json.dumps(
                            {"reviewer": reviewer, "candidates": evidence},
                            ensure_ascii=False,
                            default=str,
                        ),
                        source_ref=f"difficulty-run:{run.id}:question:{question_number}",
                        publication_run_id=run.id,
                        updated_at=now,
                        published_at=now,
                    )
                )
            run.status = "published"
            run.updated_at = now
            run.published_at = now
            result = _row_dict(run)
        return result

    def _candidate_views(self, session: Session, run_id: str) -> list[dict[str, Any]]:
        rows = list(
            session.scalars(
                select(DifficultyEvidenceCandidateModel)
                .where(DifficultyEvidenceCandidateModel.run_id == run_id)
                .order_by(
                    DifficultyEvidenceCandidateModel.question_number,
                    DifficultyEvidenceCandidateModel.page_number,
                    DifficultyEvidenceCandidateModel.id,
                )
            )
        )
        result = []
        for row in rows:
            stored = _row_dict(row)
            review = self._latest_review(session, row.id)
            replacement = json.loads(review.replacement_json) if review is not None else {}
            item = {**stored, **replacement}
            item["review_decision"] = review.decision if review is not None else None
            item["review_replacement"] = replacement
            item["candidate_fingerprint"] = candidate_fingerprint(stored, replacement)
            item["validation_errors"] = json.loads(item["validation_errors_json"])
            result.append(item)
        return result

    @staticmethod
    def _latest_review(
        session: Session,
        candidate_id: str,
    ) -> DifficultyEvidenceReviewModel | None:
        sequence = session.scalar(
            select(func.max(DifficultyEvidenceReviewModel.sequence)).where(
                DifficultyEvidenceReviewModel.candidate_id == candidate_id
            )
        )
        if sequence is None:
            return None
        return session.scalar(
            select(DifficultyEvidenceReviewModel).where(
                DifficultyEvidenceReviewModel.candidate_id == candidate_id,
                DifficultyEvidenceReviewModel.sequence == sequence,
            )
        )

    @staticmethod
    def _validate_frozen_sources(
        session: Session,
        run: DifficultyEvidenceRunModel,
    ) -> None:
        report = session.get(SourceDocumentModel, run.source_document_id)
        question = session.get(SourceDocumentModel, run.question_paper_document_id)
        if report is None or question is None:
            raise ValueError("difficulty evidence source is no longer available")
        if report.status == "deleted" or question.status == "deleted":
            raise ValueError("archived source must be rediscovered before publication")
        if report.source_type != "examiner_report" or question.source_type != "question_paper":
            raise ValueError("difficulty evidence source types changed after extraction")
        if report.identity_status != "complete" or question.identity_status != "complete":
            raise ValueError("difficulty evidence source identity is no longer complete")
        if report.authority_tier != "official" or question.authority_tier != "official":
            raise ValueError("difficulty evidence source authority changed after extraction")
        if report.source_role != "assessment_only" or question.source_role != "assessment_only":
            raise ValueError("difficulty evidence source role changed after extraction")
        if report.checksum != run.source_checksum:
            raise ValueError("examiner report changed after extraction")
        if question.checksum != run.question_paper_checksum:
            raise ValueError("question paper changed after extraction")
        if report.subject_code != run.subject_code or question.subject_code != run.subject_code:
            raise ValueError("difficulty evidence source subject changed after extraction")
        if report.pair_key != run.pair_key or question.pair_key != run.pair_key:
            raise ValueError("difficulty evidence pair identity changed after extraction")
