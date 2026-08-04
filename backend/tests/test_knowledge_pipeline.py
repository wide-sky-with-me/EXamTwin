from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypeVar

import pytest
from examtwin.agent_harness import HarnessMessage
from examtwin.config import Settings
from examtwin.services import knowledge_pipeline
from examtwin.services.knowledge_pipeline import (
    KnowledgeBuildPipeline,
    LiteLLMSyllabusDifficultyProvider,
    SyllabusDifficultyAssessment,
)
from examtwin.services.subject_context import subject_context
from pydantic import BaseModel

StructuredResultT = TypeVar("StructuredResultT", bound=BaseModel)


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


class FakeDifficultyProvider:
    model = "fake-structured-model"
    batch_size = 20

    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def assess_batch(
        self,
        _subject_pack: Any,
        objectives: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self.batch_sizes.append(len(objectives))
        return {
            objective["code"]: SyllabusDifficultyAssessment(
                code=objective["code"],
                syllabus_complexity=0.62,
                cognitive_demand=0.68,
                prerequisite_depth=4,
                solution_steps=6,
                confidence=0.4,
                rationale="Requires several linked syllabus operations.",
            )
            for objective in objectives
        }


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
            {
                "assessments": [
                    {
                        "code": item["code"],
                        "syllabus_complexity": 0.6,
                        "cognitive_demand": 0.65,
                        "prerequisite_depth": 3,
                        "solution_steps": 5,
                        "confidence": 0.4,
                        "rationale": "Several linked syllabus operations are required.",
                    }
                    for item in request["objectives"]
                ]
            }
        )


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


def test_pipeline_publishes_validated_ai_cold_start_without_real_provider(
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
    result = KnowledgeBuildPipeline(
        Settings(object_store_local_root=storage_root),
        subject_context(Settings(object_store_local_root=storage_root)),
        repository=repository,  # type: ignore[arg-type]
        graph_repository=graph_repository,  # type: ignore[arg-type]
    ).run(
        use_ai_difficulty=True,
        difficulty_provider=provider,  # type: ignore[arg-type]
    )

    assert result["status"] == "published"
    assert result["topics"] == 38
    assert result["objectives"] == 114
    assert result["ai_assessments"] == 114
    assert len(published["difficulty_assessments"]) == 114
    assert provider.batch_sizes == [20, 20, 20, 20, 20, 14]
    assert published["candidate"].objectives[0].code == "P1.1.O01"
    assert repository.candidate_created is not None
    assert repository.candidate_created["extractor_version"] == (
        "structured-markdown-curriculum-v1"
    )
    assert any(update.get("status") == "published" for update in repository.updates)
    assert any(
        update.get("stage") == "assessing_difficulty:20/114" for update in repository.updates
    )


def test_ai_cold_start_confidence_cannot_claim_high_authority() -> None:
    with pytest.raises(ValueError):
        SyllabusDifficultyAssessment(
            code="P2.7.O01",
            syllabus_complexity=0.62,
            cognitive_demand=0.68,
            prerequisite_depth=4,
            solution_steps=6,
            confidence=0.9,
            rationale="Not allowed to look official.",
        )


def test_syllabus_difficulty_uses_the_shared_structured_harness() -> None:
    settings = Settings()
    model = FakeStructuredDifficultyModel()
    provider = LiteLLMSyllabusDifficultyProvider(settings, structured_model=model)
    subject_pack = subject_context(settings).pack

    result = provider.assess_batch(
        subject_pack,
        [
            {
                "code": "P1.1.O01",
                "parent": "P1.1",
                "title": "Use index laws.",
                "description": "Apply several index transformations.",
            }
        ],
    )

    assert list(result) == ["P1.1.O01"]
    assert isinstance(result["P1.1.O01"], SyllabusDifficultyAssessment)
    assert "D-level AI estimates" in model.messages[0].content
