from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from examtwin.knowledge.curriculum import CurriculumCandidate, get_curriculum_extractor
from examtwin.knowledge.difficulty import difficulty_label
from examtwin.knowledge.difficulty_assessment import (
    DIFFICULTY_METHOD,
    ModelDifficultyAssessment,
    validate_assessment_evidence,
)
from examtwin.knowledge.knowledge_repository import KnowledgeRepository
from examtwin.platform.database.session import utcnow
from examtwin.subjects.public import SubjectPack


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
    subject_pack: SubjectPack,
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
        Mapping[str, Any] | ModelDifficultyAssessment,
    ],
    difficulty_materials: Mapping[str, Mapping[str, Any]],
    build_run_id: str,
    input_hash: str,
    difficulty_model_name: str,
    knowledge_base_version_id: str,
) -> None:
    if candidate.subject_pack_id != subject_pack.id:
        raise ValueError(
            f"Curriculum candidate {candidate.subject_pack_id} cannot publish as {subject_pack.id}"
        )
    expected_codes = {
        *[topic.code for topic in candidate.topics],
        *[objective.code for objective in candidate.objectives],
    }
    if set(difficulty_assessments) != expected_codes:
        raise ValueError(
            "Difficulty assessments must exactly cover every Topic and Learning Objective"
        )
    if set(difficulty_materials) != expected_codes:
        raise ValueError(
            "Difficulty evidence materials must exactly cover every rated knowledge point"
        )
    assessments: dict[str, ModelDifficultyAssessment] = {}
    for code in sorted(expected_codes):
        value = difficulty_assessments[code]
        assessment = (
            value
            if isinstance(value, ModelDifficultyAssessment)
            else ModelDifficultyAssessment.model_validate(value)
        )
        validate_assessment_evidence(assessment, difficulty_materials[code])
        assessments[code] = assessment

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
        assessment = assessments[topic.code]
        source_ref = f"{candidate.source_ref}#page={topic.page}"
        point_id = _point_id(topic.code, subject_pack)
        features = _difficulty_features(
            assessment,
            difficulty_materials[topic.code],
            node_type="topic",
            description=f"Official syllabus topic {topic.code}",
            syllabus_page=topic.page,
            parent_topic=None,
            candidate=candidate,
            build_run_id=build_run_id,
            input_hash=input_hash,
            knowledge_base_version_id=knowledge_base_version_id,
        )
        points.append(
            {
                "id": point_id,
                "subject_code": subject_pack.subject_code,
                "code": topic.code,
                "title": topic.title,
                "unit_code": topic.unit_code,
                "strand": topic.strand,
                "parent_id": _point_id(topic.unit_code, subject_pack),
                "difficulty_score": assessment.difficulty_score,
                "difficulty_label": difficulty_label(assessment.difficulty_score),
                "difficulty_confidence": assessment.confidence,
                "evidence_level": "D",
                "source_ref": source_ref,
                "features_json": json.dumps(features, ensure_ascii=False),
                "updated_at": now,
            }
        )
        difficulty_rows.append(
            _difficulty_evidence_row(
                point_id=point_id,
                source_ref=source_ref,
                assessment=assessment,
                material=difficulty_materials[topic.code],
                build_run_id=build_run_id,
                input_hash=input_hash,
                model_name=difficulty_model_name,
                knowledge_base_version_id=knowledge_base_version_id,
                now=now,
            )
        )
        relations.append(
            _relation(
                topic.unit_code,
                topic.code,
                "contains",
                1.0,
                source_ref,
                subject_pack,
            )
        )

    previous_by_parent: dict[str, str] = {}
    unit_titles = {unit.code: unit.title for unit in candidate.units}
    for objective in objectives:
        parent = point_by_code[objective["parent"]]
        assessment = assessments[objective["code"]]
        source_ref = f"{candidate.source_ref}#page={objective['page'] or parent.page}"
        point_id = _point_id(objective["code"], subject_pack)
        features = _difficulty_features(
            assessment,
            difficulty_materials[objective["code"]],
            node_type="learning_objective",
            description=objective["description"],
            syllabus_page=objective["page"] or parent.page,
            parent_topic=parent.code,
            candidate=candidate,
            build_run_id=build_run_id,
            input_hash=input_hash,
            knowledge_base_version_id=knowledge_base_version_id,
        )
        points.append(
            {
                "id": point_id,
                "subject_code": subject_pack.subject_code,
                "code": objective["code"],
                "title": objective["title"],
                "unit_code": parent.unit_code,
                "strand": parent.strand,
                "parent_id": _point_id(parent.code, subject_pack),
                "difficulty_score": assessment.difficulty_score,
                "difficulty_label": difficulty_label(assessment.difficulty_score),
                "difficulty_confidence": assessment.confidence,
                "evidence_level": "D",
                "source_ref": source_ref,
                "features_json": json.dumps(features, ensure_ascii=False),
                "updated_at": now,
            }
        )
        difficulty_rows.append(
            _difficulty_evidence_row(
                point_id=point_id,
                source_ref=source_ref,
                assessment=assessment,
                material=difficulty_materials[objective["code"]],
                build_run_id=build_run_id,
                input_hash=input_hash,
                model_name=difficulty_model_name,
                knowledge_base_version_id=knowledge_base_version_id,
                now=now,
            )
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
        definition_document_id=str(syllabus_document["id"]),
        definitions=definitions,
        difficulty_evidence=difficulty_rows,
    )


def _difficulty_features(
    assessment: ModelDifficultyAssessment,
    material: Mapping[str, Any],
    *,
    node_type: str,
    description: str,
    syllabus_page: int | None,
    parent_topic: str | None,
    candidate: CurriculumCandidate,
    build_run_id: str,
    input_hash: str,
    knowledge_base_version_id: str,
) -> dict[str, Any]:
    return {
        **assessment.model_dump(),
        "node_type": node_type,
        "description": description,
        "syllabus_page": syllabus_page,
        "difficulty_method": DIFFICULTY_METHOD,
        "difficulty_rationale": assessment.rationale,
        "difficulty_run_id": build_run_id,
        "difficulty_input_hash": input_hash,
        "difficulty_knowledge_base_version_id": knowledge_base_version_id,
        "difficulty_evidence_blocks": _evidence_metadata(material),
        "parent_topic": parent_topic,
        "curriculum_extractor_version": candidate.extractor_version,
        "curriculum_candidate_hash": candidate.content_hash,
    }


def _difficulty_evidence_row(
    *,
    point_id: str,
    source_ref: str,
    assessment: ModelDifficultyAssessment,
    material: Mapping[str, Any],
    build_run_id: str,
    input_hash: str,
    model_name: str,
    knowledge_base_version_id: str,
    now: Any,
) -> dict[str, Any]:
    return {
        "knowledge_point_id": point_id,
        "question_ref": None,
        "evidence_type": "model_content_cold_start",
        "value": assessment.difficulty_score,
        "evidence_level": "D",
        "source_ref": source_ref,
        "notes": assessment.rationale,
        "created_at": now,
        "run_id": build_run_id,
        "method_key": DIFFICULTY_METHOD,
        "model_name": model_name,
        "input_hash": input_hash,
        "details_json": json.dumps(
            {
                "assessment": assessment.model_dump(),
                "evidence_blocks": _evidence_metadata(material),
                "knowledge_base_version_id": knowledge_base_version_id,
                "pipeline_version": "curriculum-build-v3",
            },
            ensure_ascii=False,
        ),
    }


def _evidence_metadata(material: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in evidence.items() if key != "excerpt"}
        for evidence in material["evidence"]
    ]
