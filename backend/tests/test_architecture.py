from pathlib import Path

import scripts.check_architecture as architecture


def _check(tmp_path: Path, monkeypatch, relative_path: str, source: str) -> list[str]:
    package_root = tmp_path / "examtwin"
    path = package_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    monkeypatch.setattr(architecture, "PACKAGE_ROOT", package_root)
    return architecture.check_file(path)


def test_platform_cannot_import_feature(tmp_path: Path, monkeypatch) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "platform/provider.py",
        "from examtwin.assessment import grading\n",
    )

    assert any("platform must not depend on feature" in error for error in errors)


def test_feature_cannot_import_app(tmp_path: Path, monkeypatch) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "knowledge/service.py",
        "from examtwin.app.api import dependencies\n",
    )

    assert any("feature must not depend on app" in error for error in errors)


def test_feature_dependencies_follow_subjects_knowledge_assessment_order(
    tmp_path: Path,
    monkeypatch,
) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "knowledge/service.py",
        "from examtwin.assessment import grading\n",
    )

    assert any(
        "knowledge must not depend on downstream feature assessment" in error for error in errors
    )


def test_cross_feature_imports_use_public_entrypoint(tmp_path: Path, monkeypatch) -> None:
    internal_errors = _check(
        tmp_path,
        monkeypatch,
        "assessment/service.py",
        "from examtwin.knowledge.rag import RagService\n",
    )
    public_errors = _check(
        tmp_path,
        monkeypatch,
        "assessment/service.py",
        "from examtwin.knowledge.public import KnowledgeRepository\n",
    )

    assert any(
        "cross-feature imports must use knowledge.public" in error for error in internal_errors
    )
    assert public_errors == []


def test_fastapi_is_restricted_to_app(tmp_path: Path, monkeypatch) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "assessment/grading.py",
        "from fastapi import HTTPException\n",
    )

    assert any("FastAPI is restricted to the app boundary" in error for error in errors)


def test_legacy_horizontal_module_is_rejected(tmp_path: Path, monkeypatch) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "services/rag.py",
        "VALUE = 1\n",
    )

    assert any("legacy horizontal module is forbidden" in error for error in errors)


def test_app_may_compose_features(tmp_path: Path, monkeypatch) -> None:
    errors = _check(
        tmp_path,
        monkeypatch,
        "app/composition.py",
        "from examtwin.knowledge import rag\nfrom fastapi import Depends\n",
    )

    assert errors == []
