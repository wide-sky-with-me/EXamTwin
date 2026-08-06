from __future__ import annotations

from typing import Any

import pytest
from examtwin.knowledge.difficulty_assessment import (
    DifficultyCitation,
    ModelDifficultyAssessment,
    build_evidence_materials,
    difficulty_input_hash,
    validate_assessment_evidence,
)


def _target() -> dict[str, Any]:
    return {
        "code": "U1.1.O01",
        "parent": "U1.1",
        "unit_code": "U1",
        "unit_title": "Markets and market failure",
        "node_type": "learning_objective",
        "title": "Explain price elasticity of demand",
        "description": "Calculate and interpret elasticity coefficients.",
        "child_codes": [],
    }


def _block(
    block_id: str,
    source_type: str,
    content: str,
    *,
    authority_tier: str,
    knowledge_codes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": block_id,
        "document_id": f"document-{block_id}",
        "page": 10,
        "section": "Price elasticity of demand",
        "section_path": ["Markets", "Elasticity"],
        "content": content,
        "content_hash": f"hash-{block_id}",
        "knowledge_codes": knowledge_codes or [],
        "metadata": {"source_type": source_type, "authority_tier": authority_tier},
    }


def _assessment(material: dict[str, Any], *, quote: str) -> ModelDifficultyAssessment:
    citations = [
        DifficultyCitation.model_validate(
            {
                "block_id": evidence["block_id"],
                "evidence_role": evidence["evidence_role"],
                "quote": quote,
            }
        )
        for evidence in material["evidence"]
    ]
    return ModelDifficultyAssessment(
        code="U1.1.O01",
        evidence_sufficient=True,
        difficulty_score=0.57,
        relative_position=0.54,
        cognitive_demand=0.62,
        abstraction=0.45,
        prerequisite_breadth=2,
        procedural_depth=4,
        representation_switching=0.3,
        expected_steps=4,
        common_misconceptions=["Reverses the sign interpretation."],
        confidence=0.4,
        rationale="Both sources require calculation and interpretation.",
        citations=citations,
    )


def test_material_builder_uses_only_official_and_licensed_core_blocks() -> None:
    quote = "Elasticity requires calculation and interpretation of coefficients."
    materials = build_evidence_materials(
        [_target()],
        [
            _block("syllabus", "syllabus", quote, authority_tier="official"),
            _block("licensed", "textbook", quote, authority_tier="licensed_core"),
            _block(
                "unlicensed",
                "textbook",
                quote,
                authority_tier="supplementary",
                knowledge_codes=["U1.1.O01"],
            ),
        ],
    )

    evidence = materials["U1.1.O01"]["evidence"]
    assert {(item["block_id"], item["evidence_role"]) for item in evidence} == {
        ("syllabus", "syllabus"),
        ("licensed", "textbook"),
    }


def test_material_builder_fails_without_both_source_roles() -> None:
    with pytest.raises(ValueError, match="textbook"):
        build_evidence_materials(
            [_target()],
            [
                _block(
                    "syllabus",
                    "syllabus",
                    "Elasticity calculation and interpretation.",
                    authority_tier="official",
                )
            ],
        )


def test_assessment_citations_must_be_verbatim_and_cover_both_roles() -> None:
    quote = "Elasticity requires calculation and interpretation of coefficients."
    material = build_evidence_materials(
        [_target()],
        [
            _block("syllabus", "syllabus", quote, authority_tier="official"),
            _block("textbook", "textbook", quote, authority_tier="licensed_core"),
        ],
    )["U1.1.O01"]

    validate_assessment_evidence(_assessment(material, quote=quote), material)
    with pytest.raises(ValueError, match="verbatim"):
        validate_assessment_evidence(
            _assessment(material, quote="This sentence was not present in either supplied block."),
            material,
        )


def test_difficulty_cache_hash_is_bound_to_core_version() -> None:
    quote = "Elasticity requires calculation and interpretation of coefficients."
    material = build_evidence_materials(
        [_target()],
        [
            _block("syllabus", "syllabus", quote, authority_tier="official"),
            _block("textbook", "textbook", quote, authority_tier="licensed_core"),
        ],
    )

    first = difficulty_input_hash(
        candidate_hash="candidate",
        knowledge_base_version_id="core-v1",
        materials=material,
    )
    second = difficulty_input_hash(
        candidate_hash="candidate",
        knowledge_base_version_id="core-v2",
        materials=material,
    )

    assert first != second
