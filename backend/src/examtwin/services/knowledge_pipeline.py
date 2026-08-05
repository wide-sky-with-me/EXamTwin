from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from examtwin.agent_harness import StructuredModelPort, StructuredTask, StructuredTaskRunner
from examtwin.config import Settings
from examtwin.persistence.knowledge_build_repository import KnowledgeBuildRepository
from examtwin.persistence.knowledge_repository import KnowledgeRepository
from examtwin.persistence.session import utcnow
from examtwin.prompt_templates import load_prompt_template
from examtwin.services.cache_paths import resolve_markdown_cache_path
from examtwin.services.curriculum import (
    MINERU_MARKDOWN_PROJECTION,
    PDF_TEXT_PROJECTION,
    CurriculumCandidate,
    CurriculumExtraction,
    CurriculumValidation,
    pdf_text_curriculum_projection,
    select_curriculum_projection,
)
from examtwin.services.knowledge_publication import publish_curriculum_graph
from examtwin.services.structured_model import LiteLLMStructuredModel
from examtwin.services.subject_context import SubjectContext
from examtwin.subjects import SubjectPack
from pydantic import BaseModel, ConfigDict, Field

PIPELINE_VERSION = "curriculum-build-v2"
AI_DIFFICULTY_METHOD = "syllabus-ai-feature-estimate-v1"


class CurriculumReviewRequired(ValueError):
    pass


class SyllabusDifficultyAssessment(BaseModel):
    """Auditable D-level feature estimate, never an official difficulty rating."""

    model_config = ConfigDict(extra="forbid", strict=True)

    code: str = Field(min_length=1, max_length=80)
    syllabus_complexity: float = Field(ge=0, le=1)
    cognitive_demand: float = Field(ge=0, le=1)
    prerequisite_depth: int = Field(ge=0, le=12)
    solution_steps: int = Field(ge=1, le=20)
    confidence: float = Field(ge=0.05, le=0.45)
    rationale: str = Field(min_length=1, max_length=500)


class SyllabusDifficultyBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    assessments: list[SyllabusDifficultyAssessment] = Field(min_length=1, max_length=50)


class SyllabusDifficultyProvider(Protocol):
    model: str
    batch_size: int

    def assess_batch(
        self,
        subject_pack: SubjectPack,
        objectives: Sequence[Mapping[str, Any]],
    ) -> dict[str, SyllabusDifficultyAssessment]: ...


class LiteLLMSyllabusDifficultyProvider:
    """Use provider-constrained JSON to estimate syllabus features in bounded batches."""

    def __init__(
        self,
        settings: Settings,
        *,
        structured_model: StructuredModelPort | None = None,
    ) -> None:
        credential = settings.llm_provider_api_key
        if structured_model is None and (credential is None or not credential.get_secret_value()):
            raise RuntimeError("LLM credential is required for AI syllabus difficulty")
        self.model = settings.knowledge_difficulty_model
        self.api_base = settings.llm_provider_base_url
        self.api_key = "" if credential is None else credential.get_secret_value()
        self.reasoning_effort = settings.knowledge_difficulty_reasoning_effort
        self.timeout = settings.knowledge_difficulty_timeout
        self.batch_size = settings.knowledge_difficulty_batch_size
        self.runner = StructuredTaskRunner(
            structured_model
            or LiteLLMStructuredModel(
                model=self.model,
                api_base=self.api_base,
                api_key=self.api_key,
                reasoning_effort=self.reasoning_effort,
                max_retries=1,
            )
        )

    def assess_batch(
        self,
        subject_pack: SubjectPack,
        objectives: Sequence[Mapping[str, Any]],
    ) -> dict[str, SyllabusDifficultyAssessment]:
        if not objectives or len(objectives) > self.batch_size:
            raise ValueError(f"AI difficulty batch must contain 1..{self.batch_size} objectives")
        expected = {str(item["code"]) for item in objectives}
        task = StructuredTask(
            system_prompt=load_prompt_template("difficulty/SYSTEM.md"),
            user_content=json.dumps(
                {
                    "subject": subject_pack.title,
                    "objectives": [
                        {
                            "code": item["code"],
                            "parent": item["parent"],
                            "title": item["title"],
                            "description": item.get("description", ""),
                        }
                        for item in objectives
                    ],
                },
                ensure_ascii=False,
            ),
        )
        payload = self.runner.run(task, SyllabusDifficultyBatch, timeout=self.timeout)
        actual = {item.code for item in payload.assessments}
        if actual != expected or len(payload.assessments) != len(expected):
            missing = sorted(expected - actual)
            unexpected = sorted(actual - expected)
            raise ValueError(
                f"AI difficulty batch code mismatch; missing={missing}, unexpected={unexpected}"
            )
        return {item.code: item for item in payload.assessments}


class KnowledgeBuildPipeline:
    """Build and transactionally publish one subject's syllabus knowledge graph."""

    def __init__(
        self,
        settings: Settings,
        subject: SubjectContext,
        repository: KnowledgeBuildRepository,
        graph_repository: KnowledgeRepository,
    ) -> None:
        self.settings = settings
        self.subject_pack = subject.pack
        self.repository = repository
        self.graph_repository = graph_repository

    def run(
        self,
        *,
        use_ai_difficulty: bool = False,
        difficulty_provider: SyllabusDifficultyProvider | None = None,
    ) -> dict[str, Any]:
        run_id = str(uuid.uuid4())
        now = utcnow()
        provider = difficulty_provider
        if use_ai_difficulty and provider is None:
            provider = LiteLLMSyllabusDifficultyProvider(self.settings)
        self.repository.create_run(
            {
                "id": run_id,
                "subject_pack_id": self.subject_pack.id,
                "subject_code": self.subject_pack.subject_code,
                "source_document_id": None,
                "status": "running",
                "stage": "loading_syllabus",
                "pipeline_version": PIPELINE_VERSION,
                "input_hash": None,
                "ai_model": provider.model if provider else None,
                "config_json": json.dumps({"use_ai_difficulty": use_ai_difficulty}),
                "metrics_json": "{}",
                "artifact_json": "{}",
                "error": None,
                "created_at": now,
                "updated_at": now,
                "completed_at": None,
            }
        )
        candidate_id: str | None = None
        try:
            document = self._syllabus_document()
            extraction, markdown_path = self._curriculum_extraction(document)
            candidate = extraction.candidate
            validation = extraction.validation
            input_hash = candidate.input_hash
            new_candidate_id = str(uuid.uuid4())
            candidate_now = utcnow()
            auto_publish = validation.passed and not validation.warnings
            candidate_status = (
                "ready" if auto_publish else "needs_review" if validation.passed else "rejected"
            )
            self.repository.create_candidate(
                {
                    "id": new_candidate_id,
                    "build_run_id": run_id,
                    "subject_pack_id": self.subject_pack.id,
                    "subject_code": self.subject_pack.subject_code,
                    "source_document_id": str(document["id"]),
                    "input_hash": input_hash,
                    "content_hash": candidate.content_hash,
                    "extractor_version": candidate.extractor_version,
                    "status": candidate_status,
                    "review_status": "auto_approved" if auto_publish else "required",
                    "candidate_json": candidate.model_dump_json(),
                    "validation_json": validation.model_dump_json(),
                    "created_at": candidate_now,
                    "updated_at": candidate_now,
                    "published_at": None,
                }
            )
            candidate_id = new_candidate_id
            if not auto_publish:
                reasons = [*validation.errors, *validation.warnings]
                raise CurriculumReviewRequired(
                    "Curriculum candidate requires review: " + "; ".join(reasons)
                )
            objectives = [objective.model_dump() for objective in candidate.objectives]
            artifact = {
                "candidate_id": candidate_id,
                "candidate_hash": candidate.content_hash,
                "extractor_version": candidate.extractor_version,
                "unit_codes": [unit.code for unit in candidate.units],
                "topic_codes": [topic.code for topic in candidate.topics],
                "objective_codes": [item["code"] for item in objectives],
                "source_path": str(markdown_path),
                "source_projection": extraction.projection,
                "validation": validation.model_dump(),
            }
            self._update_run(
                run_id,
                stage="assessing_difficulty" if provider else "publishing",
                source_document_id=str(document["id"]),
                input_hash=input_hash,
                artifact_json=json.dumps(artifact, ensure_ascii=False),
            )

            assessments: dict[str, SyllabusDifficultyAssessment] = {}
            ai_reused = False
            if provider:
                assessments = self._cached_assessments(
                    input_hash,
                    provider.model,
                )
                ai_reused = bool(assessments)
                cached_count = len(assessments)
                pending = [item for item in objectives if item["code"] not in assessments]
                for offset in range(0, len(pending), provider.batch_size):
                    batch = pending[offset : offset + provider.batch_size]
                    batch_results = provider.assess_batch(self.subject_pack, batch)
                    assessments.update(batch_results)
                    artifact["difficulty_assessments"] = [
                        assessments[code].model_dump() for code in sorted(assessments)
                    ]
                    self._update_run(
                        run_id,
                        stage=f"assessing_difficulty:{len(assessments)}/{len(objectives)}",
                        metrics_json=json.dumps(
                            {
                                "objectives": len(objectives),
                                "ai_assessments": len(assessments),
                                "ai_reused_count": cached_count,
                            }
                        ),
                        artifact_json=json.dumps(artifact, ensure_ascii=False),
                    )
                expected = {str(item["code"]) for item in objectives}
                if set(assessments) != expected:
                    raise ValueError(
                        "AI difficulty provider did not assess every syllabus objective"
                    )
                artifact["difficulty_assessments"] = [
                    assessments[code].model_dump() for code in sorted(assessments)
                ]
                self._update_run(
                    run_id,
                    stage="publishing",
                    artifact_json=json.dumps(artifact, ensure_ascii=False),
                )

            publish_curriculum_graph(
                self.graph_repository,
                self.subject_pack,
                candidate=candidate,
                syllabus_document=document,
                difficulty_assessments=assessments,
                build_run_id=run_id,
                input_hash=input_hash,
                difficulty_model_name=provider.model if provider else None,
            )
            metrics = {
                "units": len(candidate.units),
                "topics": len(candidate.topics),
                "objectives": len(objectives),
                "ai_assessments": len(assessments),
                "ai_reused": ai_reused,
                "difficulty_evidence_level": "D",
            }
            completed_at = utcnow()
            self.repository.update_candidate(
                candidate_id,
                {
                    "status": "published",
                    "review_status": "auto_approved",
                    "updated_at": completed_at,
                    "published_at": completed_at,
                },
            )
            self._update_run(
                run_id,
                status="published",
                stage="published",
                metrics_json=json.dumps(metrics),
                completed_at=completed_at,
            )
            return {"run_id": run_id, "status": "published", **metrics}
        except Exception as error:
            if candidate_id is not None and not isinstance(error, CurriculumReviewRequired):
                self.repository.update_candidate(
                    candidate_id,
                    {
                        "status": "failed",
                        "updated_at": utcnow(),
                    },
                )
            self._update_run(
                run_id,
                status="failed",
                stage="failed",
                error=str(error)[:2000],
                completed_at=utcnow(),
            )
            raise

    def preview(self) -> dict[str, Any]:
        """Extract and validate a candidate without persisting or publishing it."""
        document = self._syllabus_document()
        extraction, _markdown_path = self._curriculum_extraction(document)
        candidate = extraction.candidate
        validation = extraction.validation
        return {
            "candidate": candidate.model_dump(),
            "candidate_hash": candidate.content_hash,
            "source_projection": extraction.projection,
            "validation": validation.model_dump(),
            "publishable": validation.passed and not validation.warnings,
        }

    def _curriculum_extraction(
        self,
        document: Mapping[str, Any],
    ) -> tuple[CurriculumExtraction, Path]:
        markdown_path = resolve_markdown_cache_path(
            self.settings,
            str(document["id"]),
            str(document["markdown_path"]),
        )
        projections = [
            (MINERU_MARKDOWN_PROJECTION, markdown_path.read_text(encoding="utf-8")),
        ]
        source_path = Path(str(document["path"])).resolve()
        if source_path.suffix.lower() == ".pdf" and source_path.is_file():
            projections.append((PDF_TEXT_PROJECTION, pdf_text_curriculum_projection(source_path)))
        extraction = select_curriculum_projection(
            projections,
            self.subject_pack,
            source_document_id=str(document["id"]),
            source_ref=str(document["path"]),
        )
        self._apply_published_graph_gate(extraction.candidate, extraction.validation)
        return extraction, markdown_path

    def _syllabus_document(self) -> dict[str, Any]:
        row = self.repository.syllabus_document(self.subject_pack.subject_code)
        if not row:
            raise LookupError(
                f"No converted syllabus is available for {self.subject_pack.subject_code}"
            )
        return row

    def _apply_published_graph_gate(
        self,
        candidate: CurriculumCandidate,
        validation: CurriculumValidation,
    ) -> None:
        published = self.repository.published_graph_codes(self.subject_pack.subject_code)
        candidate_topics = {topic.code for topic in candidate.topics}
        candidate_objectives = {objective.code for objective in candidate.objectives}
        missing_topics = sorted(published["topics"] - candidate_topics)
        missing_objectives = sorted(published["objectives"] - candidate_objectives)
        if missing_topics:
            validation.errors.append(f"published topics disappeared: {missing_topics}")
        if missing_objectives:
            validation.errors.append(f"published objectives disappeared: {missing_objectives[:20]}")
        validation.passed = not validation.errors

    def _cached_assessments(
        self,
        input_hash: str,
        model: str,
    ) -> dict[str, SyllabusDifficultyAssessment]:
        merged: dict[str, SyllabusDifficultyAssessment] = {}
        for value in self.repository.cached_artifacts(
            subject_code=self.subject_pack.subject_code,
            input_hash=input_hash,
            ai_model=model,
        ):
            try:
                artifact = json.loads(value or "{}")
                items = artifact.get("difficulty_assessments", [])
                assessments = [SyllabusDifficultyAssessment.model_validate(item) for item in items]
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            for assessment in assessments:
                merged.setdefault(assessment.code, assessment)
        return merged

    def _update_run(self, run_id: str, **updates: Any) -> None:
        if not updates:
            return
        updates["updated_at"] = utcnow()
        self.repository.update_run(run_id, updates)
