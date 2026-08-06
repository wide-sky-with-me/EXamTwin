from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from examtwin.config import Settings
from examtwin.persistence.document_block_repository import DocumentBlockRepository
from examtwin.persistence.knowledge_build_repository import KnowledgeBuildRepository
from examtwin.persistence.knowledge_repository import KnowledgeRepository
from examtwin.persistence.session import utcnow
from examtwin.persistence.workspace_repository import WorkspaceRepository
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
from examtwin.services.difficulty_assessment import (
    DIFFICULTY_METHOD,
    DifficultyAssessmentProvider,
    LiteLLMDifficultyAssessmentProvider,
    ModelDifficultyAssessment,
    build_difficulty_targets,
    build_evidence_materials,
    difficulty_input_hash,
    validate_assessment_evidence,
)
from examtwin.services.knowledge_publication import publish_curriculum_graph
from examtwin.services.subject_context import SubjectContext

PIPELINE_VERSION = "curriculum-build-v3"


class CurriculumReviewRequired(ValueError):
    pass


class KnowledgeBuildPipeline:
    """Build and transactionally publish one subject's evidence-rated curriculum graph."""

    def __init__(
        self,
        settings: Settings,
        subject: SubjectContext,
        repository: KnowledgeBuildRepository,
        graph_repository: KnowledgeRepository,
        workspace_repository: WorkspaceRepository,
        block_repository: DocumentBlockRepository,
    ) -> None:
        self.settings = settings
        self.subject_pack = subject.pack
        self.repository = repository
        self.graph_repository = graph_repository
        self.workspace_repository = workspace_repository
        self.block_repository = block_repository

    def run(
        self,
        *,
        difficulty_provider: DifficultyAssessmentProvider | None = None,
    ) -> dict[str, Any]:
        run_id = str(uuid.uuid4())
        now = utcnow()
        provider = difficulty_provider or LiteLLMDifficultyAssessmentProvider(self.settings)
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
                "ai_model": provider.model,
                "config_json": json.dumps({"difficulty_method": DIFFICULTY_METHOD}),
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
            curriculum_input_hash = candidate.input_hash
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
                    "input_hash": curriculum_input_hash,
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
            targets = build_difficulty_targets(candidate)
            knowledge_base_version_id = self._core_knowledge_base_version_id()
            blocks = self.block_repository.list_for_version(
                knowledge_base_version_id,
                limit=None,
            )
            materials = build_evidence_materials(targets, blocks)
            assessment_input_hash = difficulty_input_hash(
                candidate_hash=candidate.content_hash,
                knowledge_base_version_id=knowledge_base_version_id,
                materials=materials,
            )
            artifact = {
                "candidate_id": candidate_id,
                "candidate_hash": candidate.content_hash,
                "curriculum_input_hash": curriculum_input_hash,
                "extractor_version": candidate.extractor_version,
                "unit_codes": [unit.code for unit in candidate.units],
                "topic_codes": [topic.code for topic in candidate.topics],
                "objective_codes": [item["code"] for item in objectives],
                "difficulty_target_codes": [str(item["code"]) for item in targets],
                "difficulty_input_hash": assessment_input_hash,
                "difficulty_method": DIFFICULTY_METHOD,
                "knowledge_base_version_id": knowledge_base_version_id,
                "evidence_block_count": len(blocks),
                "source_path": str(markdown_path),
                "source_projection": extraction.projection,
                "validation": validation.model_dump(),
            }
            self._update_run(
                run_id,
                stage="assessing_difficulty",
                source_document_id=str(document["id"]),
                input_hash=assessment_input_hash,
                artifact_json=json.dumps(artifact, ensure_ascii=False),
            )

            assessments = self._cached_assessments(
                assessment_input_hash,
                provider.model,
                materials,
            )
            cached_count = len(assessments)
            for unit in candidate.units:
                unit_targets = [
                    materials[str(target["code"])]
                    for target in targets
                    if target["unit_code"] == unit.code
                ]
                pending = [item for item in unit_targets if item["code"] not in assessments]
                for offset in range(0, len(pending), provider.batch_size):
                    batch = pending[offset : offset + provider.batch_size]
                    batch_results = provider.assess_batch(
                        self.subject_pack,
                        unit_outline=unit_targets,
                        targets=batch,
                    )
                    assessments.update(batch_results)
                    artifact["difficulty_assessments"] = [
                        assessments[code].model_dump() for code in sorted(assessments)
                    ]
                    self._update_run(
                        run_id,
                        stage=f"assessing_difficulty:{len(assessments)}/{len(targets)}",
                        metrics_json=json.dumps(
                            {
                                "difficulty_targets": len(targets),
                                "ai_assessments": len(assessments),
                                "ai_reused_count": cached_count,
                            }
                        ),
                        artifact_json=json.dumps(artifact, ensure_ascii=False),
                    )

            expected = {str(item["code"]) for item in targets}
            if set(assessments) != expected:
                raise ValueError(
                    "Difficulty provider did not assess every Topic and Learning Objective"
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
                difficulty_materials=materials,
                build_run_id=run_id,
                input_hash=assessment_input_hash,
                difficulty_model_name=provider.model,
                knowledge_base_version_id=knowledge_base_version_id,
            )
            metrics = {
                "units": len(candidate.units),
                "topics": len(candidate.topics),
                "objectives": len(objectives),
                "difficulty_targets": len(targets),
                "ai_assessments": len(assessments),
                "ai_reused": cached_count == len(targets),
                "ai_reused_count": cached_count,
                "difficulty_evidence_level": "D",
                "difficulty_method": DIFFICULTY_METHOD,
                "knowledge_base_version_id": knowledge_base_version_id,
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

    def _core_knowledge_base_version_id(self) -> str:
        subject = self.workspace_repository.require_subject(self.subject_pack.id)
        core = next(
            (base for base in subject["knowledge_bases"] if base["kind"] == "core"),
            None,
        )
        active = None if core is None else core.get("active_version")
        if not isinstance(active, Mapping) or active.get("status") != "published":
            raise LookupError(
                "No published core knowledge base is available for "
                f"{self.subject_pack.subject_code}"
            )
        return str(active["id"])

    def _cached_assessments(
        self,
        input_hash: str,
        model: str,
        materials: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, ModelDifficultyAssessment]:
        merged: dict[str, ModelDifficultyAssessment] = {}
        for value in self.repository.cached_artifacts(
            subject_code=self.subject_pack.subject_code,
            input_hash=input_hash,
            ai_model=model,
        ):
            try:
                artifact = json.loads(value or "{}")
                items = artifact.get("difficulty_assessments", [])
                assessments = [ModelDifficultyAssessment.model_validate(item) for item in items]
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            for assessment in assessments:
                material = materials.get(assessment.code)
                if material is None:
                    continue
                try:
                    validate_assessment_evidence(assessment, material)
                except ValueError:
                    continue
                merged.setdefault(assessment.code, assessment)
        return merged

    def _update_run(self, run_id: str, **updates: Any) -> None:
        if not updates:
            return
        updates["updated_at"] = utcnow()
        self.repository.update_run(run_id, updates)
