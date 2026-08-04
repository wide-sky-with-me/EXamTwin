from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Protocol

from examtwin.persistence.knowledge_repository import KnowledgeRepository
from examtwin.persistence.session import utcnow
from examtwin.schemas.knowledge import DifficultyFeatures
from examtwin.services.curriculum import CurriculumCandidate, get_curriculum_extractor
from examtwin.services.difficulty import (
    DIFFICULTY_ALGORITHM_VERSION,
    calculate_difficulty,
    derive_objective_features,
)
from examtwin.subjects import OXFORDAQA_MATHEMATICS_9660, SubjectPack


class _ModelDumpable(Protocol):
    def model_dump(self) -> dict[str, Any]: ...


def _point_id(
    code: str,
    subject_pack: SubjectPack,
) -> str:
    return subject_pack.point_id(code)


def _relation(
    source_code: str,
    target_code: str,
    relation_type: str,
    confidence: float,
    source_ref: str,
    subject_pack: SubjectPack,
) -> dict[str, Any]:
    return {
        "source_id": _point_id(source_code, subject_pack),
        "target_id": _point_id(target_code, subject_pack),
        "relation_type": relation_type,
        "confidence": confidence,
        "source_ref": source_ref,
    }


def extract_syllabus_objectives(
    markdown: str,
    subject_pack: SubjectPack = OXFORDAQA_MATHEMATICS_9660,
) -> list[dict[str, Any]]:
    """Compatibility projection from the reusable curriculum extractor."""
    candidate = get_curriculum_extractor(subject_pack).extract(
        markdown,
        subject_pack,
        source_document_id="compatibility-extraction",
        source_ref=subject_pack.specification_ref,
        input_hash=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
    )
    return [objective.model_dump() for objective in candidate.objectives]


def publish_curriculum_graph(
    repository: KnowledgeRepository,
    subject_pack: SubjectPack,
    *,
    candidate: CurriculumCandidate,
    syllabus_document: Mapping[str, Any],
    difficulty_assessments: Mapping[
        str,
        Mapping[str, Any] | _ModelDumpable,
    ]
    | None = None,
    build_run_id: str | None = None,
    input_hash: str | None = None,
    difficulty_model_name: str | None = None,
) -> None:
    if candidate.subject_pack_id != subject_pack.id:
        raise ValueError(
            f"Curriculum candidate {candidate.subject_pack_id} cannot publish as {subject_pack.id}"
        )
    now = utcnow()
    objectives = [objective.model_dump() for objective in candidate.objectives]
    point_by_code = {point.code: point for point in candidate.topics}
    points: list[dict[str, Any]] = [
        {
            "id": _point_id("ROOT", subject_pack),
            "subject_code": subject_pack.subject_code,
            "code": "ROOT",
            "title": subject_pack.title,
            "unit_code": subject_pack.subject_code,
            "strand": "Subject",
            "parent_id": None,
            "difficulty_score": 0.5,
            "difficulty_label": "medium",
            "difficulty_confidence": 1.0,
            "evidence_level": "A",
            "source_ref": f"{subject_pack.specification_ref}#page=3",
            "features_json": json.dumps({"node_type": "subject"}),
            "updated_at": now,
        }
    ]
    relations: list[dict[str, Any]] = []
    definitions: list[dict[str, Any]] = []
    difficulty_rows: list[dict[str, Any]] = []

    for unit in candidate.units:
        points.append(
            {
                "id": _point_id(unit.code, subject_pack),
                "subject_code": subject_pack.subject_code,
                "code": unit.code,
                "title": unit.title,
                "unit_code": unit.code,
                "strand": unit.strand,
                "parent_id": _point_id("ROOT", subject_pack),
                "difficulty_score": 0.5,
                "difficulty_label": "medium",
                "difficulty_confidence": 0.7,
                "evidence_level": "A",
                "source_ref": f"{candidate.source_ref}#page={unit.page}",
                "features_json": json.dumps({"node_type": "unit", "syllabus_page": unit.page}),
                "updated_at": now,
            }
        )
        relations.append(
            _relation(
                "ROOT",
                unit.code,
                "contains",
                1.0,
                f"{candidate.source_ref}#page={unit.page}",
                subject_pack,
            )
        )

    for topic in candidate.topics:
        features = DifficultyFeatures(
            syllabus_complexity=topic.syllabus_complexity,
            prerequisite_depth=topic.prerequisite_depth,
            cognitive_demand=topic.cognitive_demand,
            solution_steps=topic.solution_steps,
            evidence_confidence=0.35,
        )
        result = calculate_difficulty(features)
        points.append(
            {
                "id": _point_id(topic.code, subject_pack),
                "subject_code": subject_pack.subject_code,
                "code": topic.code,
                "title": topic.title,
                "unit_code": topic.unit_code,
                "strand": topic.strand,
                "parent_id": _point_id(topic.unit_code, subject_pack),
                "difficulty_score": result.score,
                "difficulty_label": result.label,
                "difficulty_confidence": result.confidence,
                "evidence_level": "D",
                "source_ref": f"{candidate.source_ref}#page={topic.page}",
                "features_json": json.dumps(
                    {
                        **features.model_dump(),
                        "node_type": "topic",
                        "description": f"Official syllabus topic {topic.code}",
                        "syllabus_page": topic.page,
                        "curriculum_extractor_version": candidate.extractor_version,
                        "curriculum_candidate_hash": candidate.content_hash,
                    }
                ),
                "updated_at": now,
            }
        )
        relations.append(
            _relation(
                topic.unit_code,
                topic.code,
                "contains",
                1.0,
                f"{candidate.source_ref}#page={topic.page}",
                subject_pack,
            )
        )

    previous_by_parent: dict[str, str] = {}
    unit_titles = {unit.code: unit.title for unit in candidate.units}
    for objective in objectives:
        parent = point_by_code[objective["parent"]]
        assessment = (difficulty_assessments or {}).get(objective["code"])
        if assessment is None:
            assessment_data: Mapping[str, Any] | None = None
        elif isinstance(assessment, Mapping):
            assessment_data = assessment
        else:
            assessment_data = assessment.model_dump()
        if assessment_data:
            objective_features = DifficultyFeatures(
                syllabus_complexity=assessment_data["syllabus_complexity"],
                prerequisite_depth=assessment_data["prerequisite_depth"],
                cognitive_demand=assessment_data["cognitive_demand"],
                solution_steps=assessment_data["solution_steps"],
                evidence_confidence=min(0.45, assessment_data["confidence"]),
            )
            difficulty_method = "syllabus-ai-feature-estimate-v1"
            difficulty_rationale = str(assessment_data["rationale"])
        else:
            objective_features = derive_objective_features(
                parent_complexity=parent.syllabus_complexity,
                parent_depth=parent.prerequisite_depth,
                parent_cognitive=parent.cognitive_demand,
                parent_steps=parent.solution_steps,
                title=objective["title"],
                description=objective["description"],
                prerequisite_count=0,
                objective_index=objective["index"],
            )
            difficulty_method = "objective-feature-model-v2"
            difficulty_rationale = (
                "Deterministic cold-start estimate from syllabus structure and action verbs."
            )
        objective_result = calculate_difficulty(objective_features)
        source_ref = f"{candidate.source_ref}#page={objective['page'] or parent.page}"
        features = {
            **objective_features.model_dump(),
            "node_type": "learning_objective",
            "description": objective["description"],
            "syllabus_page": objective["page"] or parent.page,
            "objective_index": objective["index"],
            "difficulty_method": difficulty_method,
            "difficulty_aggregation_method": DIFFICULTY_ALGORITHM_VERSION,
            "difficulty_rationale": difficulty_rationale,
            "difficulty_contributions": objective_result.contributions,
            "difficulty_run_id": build_run_id,
            "difficulty_input_hash": input_hash,
            "parent_topic": parent.code,
            "parent_prerequisite_count": 0,
            "curriculum_extractor_version": candidate.extractor_version,
            "curriculum_candidate_hash": candidate.content_hash,
        }
        point_id = _point_id(objective["code"], subject_pack)
        points.append(
            {
                "id": point_id,
                "subject_code": subject_pack.subject_code,
                "code": objective["code"],
                "title": objective["title"],
                "unit_code": parent.unit_code,
                "strand": parent.strand,
                "parent_id": _point_id(parent.code, subject_pack),
                "difficulty_score": objective_result.score,
                "difficulty_label": objective_result.label,
                "difficulty_confidence": objective_result.confidence,
                "evidence_level": "D",
                "source_ref": source_ref,
                "features_json": json.dumps(features, ensure_ascii=False),
                "updated_at": now,
            }
        )
        relations.append(
            _relation(
                parent.code,
                objective["code"],
                "contains",
                1.0,
                source_ref,
                subject_pack,
            )
        )
        if assessment_data:
            difficulty_rows.append(
                {
                    "knowledge_point_id": point_id,
                    "question_ref": None,
                    "evidence_type": "syllabus_ai_cold_start",
                    "value": objective_result.score,
                    "evidence_level": "D",
                    "source_ref": source_ref,
                    "notes": difficulty_rationale,
                    "created_at": now,
                    "run_id": build_run_id,
                    "method_key": difficulty_method,
                    "model_name": difficulty_model_name,
                    "input_hash": input_hash,
                    "details_json": json.dumps(
                        {
                            "assessment": assessment_data,
                            "features": objective_features.model_dump(),
                            "contributions": objective_result.contributions,
                            "aggregation_method": DIFFICULTY_ALGORITHM_VERSION,
                            "pipeline_version": "curriculum-build-v2",
                        },
                        ensure_ascii=False,
                    ),
                }
            )
        if syllabus_document:
            definition = " ".join(
                part for part in (objective["title"], objective["description"]) if part
            ).strip()
            definitions.append(
                {
                    "knowledge_point_id": point_id,
                    "source_document_id": syllabus_document["id"],
                    "page": objective["page"] or parent.page,
                    "section": objective["title"],
                    "section_path_json": json.dumps(
                        [unit_titles[parent.unit_code], parent.title, objective["title"]],
                        ensure_ascii=False,
                    ),
                    "evidence_role": "definition",
                    "excerpt": definition[:4000],
                    "content_hash": hashlib.sha256(definition.encode("utf-8")).hexdigest(),
                    "confidence": 1.0,
                    "source_ref": source_ref,
                    "created_at": now,
                }
            )
        previous = previous_by_parent.get(parent.code)
        if previous:
            relations.append(
                _relation(
                    previous,
                    objective["code"],
                    "syllabus_sequence",
                    1.0,
                    source_ref,
                    subject_pack,
                )
            )
        previous_by_parent[parent.code] = objective["code"]

    repository.publish_curriculum(
        subject_code=subject_pack.subject_code,
        points=points,
        relations=relations,
        valid_objective_ids={_point_id(item["code"], subject_pack) for item in objectives},
        definition_document_id=(str(syllabus_document["id"]) if syllabus_document else None),
        definitions=definitions,
        difficulty_evidence=difficulty_rows,
    )
