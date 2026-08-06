from __future__ import annotations

import json
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, cast

import pytest
from examtwin.assessment.answering_agent.contracts import AnswerTask
from examtwin.assessment.answering_agent.prompts import compose_system_prompt
from examtwin.platform.config import Settings
from examtwin.platform.database.models import KnowledgeBaseModel
from examtwin.subjects.packages import (
    DEFAULT_SUBJECT_PACKS_ROOT,
    SubjectPackageRegistry,
    get_subject_package,
)
from examtwin.subjects.public import subject_context
from examtwin.subjects.workspace_repository import WorkspaceRepository


def test_bundled_subject_packages_load_reviewed_math_and_economics_skills() -> None:
    mathematics = get_subject_package("oxfordaqa-mathematics-9660")
    economics = get_subject_package("oxfordaqa-economics-9640")

    skill = mathematics.require_skill()
    assert mathematics.pack.subject_code == "9660"
    assert skill.required_visual_tool("Sketch the curve on the axes.") == "math_plot"
    assert skill.mandatory_tool_names == ("knowledge_search",)
    assert skill.package_digest == mathematics.digest
    assert economics.pack.subject_code == "9640"
    economics_skill = economics.require_skill()
    assert economics.answering_enabled is True
    assert (
        economics_skill.required_visual_tool(
            "With the help of a diagram, explain the difference between short-run "
            "and long-run growth."
        )
        == "economics_diagram"
    )
    assert economics_skill.required_visual_tool("Define national income.") is None
    assert economics_skill.mandatory_tool_names == ("knowledge_search",)
    assert "economics_calculate" in economics_skill.tool_names
    assert "economics_diagram" in economics_skill.tool_names


def test_subject_context_switches_runtime_bindings_without_mutating_global_settings() -> None:
    settings = Settings()
    mathematics = subject_context(settings, "9660")
    economics = subject_context(settings, "oxfordaqa-economics-9640")

    assert mathematics.vector_alias == "examtwin_9660_live"
    assert economics.subject_code == "9640"
    assert economics.vector_alias == "examtwin_9640_live"
    assert economics.corpus_dir.name == "经济"
    runtime = economics.runtime_settings(settings)
    assert runtime.subject_pack == "oxfordaqa-economics-9640"
    assert runtime.qdrant_collection_alias == "examtwin_9640_live"
    assert settings.subject_pack != runtime.subject_pack


def test_managed_subject_without_published_version_keeps_collection_and_alias_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from examtwin.subjects import public as subject_context_module

    class WorkspaceRepository:
        def __init__(self, _sessions: object) -> None:
            pass

        def resolve_subject(self, _selector: str) -> dict[str, object]:
            return {
                "id": "oxfordaqa-mathematics-9660",
                "subject_code": "9660",
                "title": "OxfordAQA International AS/A-level Mathematics (9660)",
                "board_name": "OxfordAQA International Qualifications",
                "capability_profile_id": "oxfordaqa-mathematics-9660",
                "active_graph_version_id": None,
                "knowledge_bases": [],
            }

    monkeypatch.setattr(subject_context_module, "WorkspaceRepository", WorkspaceRepository)
    context = subject_context_module.subject_context(Settings(), "9660")

    assert context.vector_collection == "examtwin_9660"
    assert context.vector_alias == "examtwin_9660_live"
    build_context = context.with_index_target(
        version_id="version-1",
        alias_name="examtwin_oxfordaqa_mathematics_9660_core_live",
    )
    runtime = build_context.runtime_settings(Settings())
    assert runtime.qdrant_collection == "examtwin_oxfordaqa_mathematics_9660_core"
    assert runtime.qdrant_collection_alias == "examtwin_oxfordaqa_mathematics_9660_core_live"

    from examtwin.app.api import system as system_api

    class MetadataWorkspaceRepository:
        def __init__(self, _sessions: object) -> None:
            pass

        def resolve_subject(self, _selector: str) -> dict[str, object]:
            return {
                "knowledge_bases": [
                    {
                        "id": "core",
                        "name": "Core Knowledge Base",
                        "kind": "core",
                        "active_version_id": "version-1",
                        "active_version": {
                            "version_number": 3,
                            "status": "published",
                            "vector_points": 5101,
                        },
                    }
                ]
            }

    monkeypatch.setattr(system_api, "WorkspaceRepository", MetadataWorkspaceRepository)
    response = system_api._subject_response(context, Settings())
    assert response.knowledge_bases[0].vector_points == 5101


def test_installed_subject_sync_creates_default_knowledge_bases() -> None:
    created: list[object] = []

    class FakeSession:
        def execute(self, _statement: object) -> None:
            pass

        def get(self, _model: type[object], _key: str) -> None:
            return None

        def add(self, value: object) -> None:
            created.append(value)

    class SessionContext(AbstractContextManager[FakeSession]):
        def __enter__(self) -> FakeSession:
            return FakeSession()

        def __exit__(self, *_args: object) -> None:
            pass

    class FakeSessionFactory:
        def begin(self) -> SessionContext:
            return SessionContext()

    repository = WorkspaceRepository(cast(Any, FakeSessionFactory()))
    repository.synchronize_installed_subjects([get_subject_package("oxfordaqa-mathematics-9660")])

    bases = [item for item in created if isinstance(item, KnowledgeBaseModel)]
    assert [(base.kind, base.name) for base in bases] == [
        ("core", "Core Knowledge Base"),
        ("supplementary", "Supplementary Knowledge Base"),
    ]


def test_subject_package_rejects_skill_path_escape(tmp_path: Path) -> None:
    package_dir = tmp_path / "oxfordaqa-mathematics-9660"
    package_dir.mkdir()
    manifest = json.loads(
        (DEFAULT_SUBJECT_PACKS_ROOT / package_dir.name / "manifest.json").read_text("utf-8")
    )
    manifest["answering"]["instructions_file"] = "../outside.md"
    (package_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "outside.md").write_text("untrusted", encoding="utf-8")

    with pytest.raises(ValueError, match="escapes its package directory"):
        SubjectPackageRegistry.from_directory(tmp_path)


def test_prompt_composition_keeps_platform_subject_and_runtime_layers_distinct() -> None:
    skill = get_subject_package("oxfordaqa-mathematics-9660").require_skill()
    p1 = compose_system_prompt(
        skill,
        AnswerTask(subject_code="9660", unit_code="P1", question="Solve it."),
    )
    p2 = compose_system_prompt(
        skill,
        AnswerTask(subject_code="9660", unit_code="P2", question="Solve it."),
    )

    assert p1.text.index("# Platform invariants") < p1.text.index("# Installed subject policy")
    assert p1.text.index("# Installed subject policy") < p1.text.index("# Runtime task data")
    assert '"unit_code": "P1"' in p1.text
    assert p1.digest != p2.digest
