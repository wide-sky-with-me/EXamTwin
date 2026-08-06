from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TypeVar

import pytest
from examtwin.agent_harness import HarnessMessage
from examtwin.config import Settings
from examtwin.services import knowledge_pipeline
from examtwin.services.difficulty_assessment import (
    LiteLLMDifficultyAssessmentProvider,
    ModelDifficultyAssessment,
)
from examtwin.services.knowledge_pipeline import KnowledgeBuildPipeline
from examtwin.services.subject_context import subject_context
from pydantic import BaseModel

StructuredResultT = TypeVar("StructuredResultT", bound=BaseModel)
_EVIDENCE_TEXT = "Topic evaluation and method evidence for linked course operations."


class FakeRepository:
    def __init__(self, markdown_path: str) -> None:
        self.markdown_path = markdown_path
        self.created: dict[str, Any] | None = None
        self.updates: list[dict[str, Any]] = []
        self.candidate_created: dict[str, Any] | None = None
        self.candidate_updates: list[dict[str, Any]] = []

    def create_run(self, values: dict[str, Any]) -> None:
        self.created = values

    def update_run(self, _run_id: str, updates: dict[str, Any]) -> None:
        self.updates.append(dict(updates))

    def syllabus_document(self, _subject_code: str) -> dict[str, Any]:
        return {
            "id": "syllabus-1",
            "path": "official/specification.pdf",
            "markdown_path": self.markdown_path,
        }

    def cached_artifacts(self, **_kwargs: Any) -> list[str]:
        return []

    def create_candidate(self, values: dict[str, Any]) -> None:
        self.candidate_created = values

    def update_candidate(self, _candidate_id: str, updates: dict[str, Any]) -> None:
        self.candidate_updates.append(dict(updates))

    def published_graph_codes(self, _subject_code: str) -> dict[str, set[str]]:
        return {"topics": set(), "objectives": set()}


class FakeWorkspaceRepository:
    def require_subject(self, _subject_id: str) -> dict[str, Any]:
        return {
            "knowledge_bases": [
                {
                    "kind": "core",
                    "active_version": {"id": "core-version-1", "status": "published"},
                }
            ]
        }


class FakeBlockRepository:
    def list_for_version(self, version_id: str, *, limit: int | None) -> list[dict[str, Any]]:
        assert version_id == "core-version-1"
        assert limit is None
        return [
            _block("syllabus-block", "syllabus", "official"),
            _block("textbook-block", "textbook", "licensed_core"),
        ]


class FakeDifficultyProvider:
    model = "fake-structured-model"
    batch_size = 20

    def __init__(self) -> None:
        self.batch_sizes: list[int] = []
        self.unit_batches: list[set[str]] = []

    def assess_batch(
        self,
        subject_pack: Any,
        *,
        unit_outline: Sequence[Mapping[str, Any]],
        targets: Sequence[Mapping[str, Any]],
    ) -> dict[str, ModelDifficultyAssessment]:
        del subject_pack
        self.batch_sizes.append(len(targets))
        self.unit_batches.append({str(target["unit_code"]) for target in targets})
        assert {str(item["unit_code"]) for item in unit_outline} == self.unit_batches[-1]
        return {str(target["code"]): _assessment(target) for target in targets}


class FakeStructuredDifficultyModel:
    model_name = "fake-difficulty-model"

    def __init__(self) -> None:
        self.messages: Sequence[HarnessMessage] = ()

    def complete(
        self,
        messages: Sequence[HarnessMessage],
        response_model: type[StructuredResultT],
        *,
        timeout: float,
    ) -> StructuredResultT:
        assert timeout > 0
        self.messages = messages
        request = json.loads(messages[1].content)
        return response_model.model_validate(
            {"assessments": [_assessment_payload(item) for item in request["targets_to_rate"]]}
        )


def _block(block_id: str, source_type: str, authority_tier: str) -> dict[str, Any]:
    return {
        "id": block_id,
        "document_id": f"{source_type}-document",
        "page": 12,
        "section": "Topic methods",
        "section_path": ["Course", "Topic methods"],
        "content": _EVIDENCE_TEXT,
        "content_hash": f"{source_type}-hash",
        "knowledge_codes": [],
        "metadata": {"source_type": source_type, "authority_tier": authority_tier},
    }


def _assessment(target: Mapping[str, Any]) -> ModelDifficultyAssessment:
    return ModelDifficultyAssessment.model_validate(_assessment_payload(target))


def _assessment_payload(target: Mapping[str, Any]) -> dict[str, Any]:
    citations = [
        {
            "block_id": evidence["block_id"],
            "evidence_role": evidence["evidence_role"],
            "quote": _EVIDENCE_TEXT,
        }
        for evidence in target["evidence"]
    ]
    return {
        "code": target["code"],
        "evidence_sufficient": True,
        "difficulty_score": 0.63,
        "relative_position": 0.58,
        "cognitive_demand": 0.66,
        "abstraction": 0.54,
        "prerequisite_breadth": 3,
        "procedural_depth": 5,
        "representation_switching": 0.42,
        "expected_steps": 6,
        "common_misconceptions": ["Confuses two linked methods."],
        "confidence": 0.4,
        "rationale": "The cited syllabus and textbook require linked operations.",
        "citations": citations,
    }


def _syllabus_cache(tmp_path: Path) -> tuple[Path, str]:
    cache = tmp_path / "corpus" / "md"
    cache.mkdir(parents=True)
    markdown = cache / "syllabus-1.md"
    topic_codes = [
        *[f"P1.{index}" for index in range(1, 6)],
        *[f"PP1.{index}" for index in range(1, 4)],
        *[f"S1.{index}" for index in range(1, 4)],
        *[f"M1.{index}" for index in range(1, 5)],
        *[f"P2.{index}" for index in range(1, 11)],
        *[f"S2.{index}" for index in range(1, 7)],
        *[f"M2.{index}" for index in range(1, 8)],
    ]
    sections = []
    for topic_index, code in enumerate(topic_codes, start=1):
        rows = "".join(
            (f"<tr><td>Evaluate {code} case {index}.</td><td>Use method {index}.</td></tr>")
            for index in range(1, 4)
        )
        sections.append(f"{code}: Topic {topic_index}\n<table>{rows}</table>")
    markdown.write_text(
        "## Page 23\n" + "\n".join(sections) + "\n",
        encoding="utf-8",
    )
    legacy = "/home/old-host/EXamTwin/var/corpus/md/syllabus-1.md"
    return tmp_path, legacy


def test_pipeline_publishes_direct_ratings_for_topics_and_objectives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root, legacy_path = _syllabus_cache(tmp_path)
    repository = FakeRepository(legacy_path)
    graph_repository = object()
    published: dict[str, Any] = {}

    def fake_publish(_repository: Any, _subject_pack: Any, **kwargs: Any) -> None:
        published.update(kwargs)

    monkeypatch.setattr(knowledge_pipeline, "publish_curriculum_graph", fake_publish)
    provider = FakeDifficultyProvider()
    settings = Settings(object_store_local_root=storage_root)
    result = KnowledgeBuildPipeline(
        settings,
        subject_context(settings),
        repository=repository,  # type: ignore[arg-type]
        graph_repository=graph_repository,  # type: ignore[arg-type]
        workspace_repository=FakeWorkspaceRepository(),  # type: ignore[arg-type]
        block_repository=FakeBlockRepository(),  # type: ignore[arg-type]
    ).run(difficulty_provider=provider)

    assert result["status"] == "published"
    assert result["topics"] == 38
    assert result["objectives"] == 114
    assert result["difficulty_targets"] == 152
    assert result["ai_assessments"] == 152
    assert len(published["difficulty_assessments"]) == 152
    assert len(published["difficulty_materials"]) == 152
    assert sum(provider.batch_sizes) == 152
    assert max(provider.batch_sizes) == 20
    assert all(len(unit_codes) == 1 for unit_codes in provider.unit_batches)
    assert published["candidate"].objectives[0].code == "P1.1.O01"
    assert published["knowledge_base_version_id"] == "core-version-1"
    assert repository.candidate_created is not None
    assert repository.candidate_created["extractor_version"] == (
        "structured-markdown-curriculum-v1"
    )
    assert any(update.get("status") == "published" for update in repository.updates)
    assert any(
        str(update.get("stage", "")).startswith("assessing_difficulty:")
        for update in repository.updates
    )


def test_model_rating_confidence_cannot_claim_high_authority() -> None:
    payload = _assessment_payload(
        {
            "code": "P2.7.O01",
            "evidence": [
                {"block_id": "s", "evidence_role": "syllabus"},
                {"block_id": "t", "evidence_role": "textbook"},
            ],
        }
    )
    payload["confidence"] = 0.9
    with pytest.raises(ValueError):
        ModelDifficultyAssessment.model_validate(payload)


def test_evidence_difficulty_uses_shared_structured_harness() -> None:
    settings = Settings()
    model = FakeStructuredDifficultyModel()
    provider = LiteLLMDifficultyAssessmentProvider(settings, structured_model=model)
    subject_pack = subject_context(settings).pack
    target = {
        "code": "P1.1.O01",
        "parent": "P1.1",
        "unit_code": "P1",
        "unit_title": "Pure Mathematics 1",
        "node_type": "learning_objective",
        "title": "Use index laws.",
        "description": "Apply several index transformations.",
        "child_codes": [],
        "evidence": [
            {
                "block_id": "syllabus-block",
                "evidence_role": "syllabus",
                "excerpt": _EVIDENCE_TEXT,
            },
            {
                "block_id": "textbook-block",
                "evidence_role": "textbook",
                "excerpt": _EVIDENCE_TEXT,
            },
        ],
    }

    result = provider.assess_batch(
        subject_pack,
        unit_outline=[target],
        targets=[target],
    )

    assert list(result) == ["P1.1.O01"]
    assert isinstance(result["P1.1.O01"], ModelDifficultyAssessment)
    assert "full Unit outline" in model.messages[0].content
    assert "targets_to_rate" in model.messages[0].content
