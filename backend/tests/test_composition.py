from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from examtwin.app import composition
from examtwin.app.api import dependencies


def test_build_corpus_workspace_service_shares_composed_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(database_url="postgresql://composition-test")
    sessions = object()
    subject = Mock()
    runtime_settings = object()
    subject.runtime_settings.return_value = runtime_settings

    documents = object()
    workspaces = object()
    object_store = object()
    ingestor = object()
    vector_indexes = object()
    knowledge = object()

    create_session_factory = Mock(return_value=sessions)
    corpus_repository = Mock(return_value=documents)
    workspace_repository = Mock(return_value=workspaces)
    build_object_store = Mock(return_value=object_store)
    corpus_ingestor = Mock(return_value=ingestor)
    vector_index_repository = Mock(return_value=vector_indexes)
    knowledge_repository = Mock(return_value=knowledge)

    monkeypatch.setattr(composition, "create_session_factory", create_session_factory)
    monkeypatch.setattr(composition, "CorpusRepository", corpus_repository)
    monkeypatch.setattr(composition, "WorkspaceRepository", workspace_repository)
    monkeypatch.setattr(composition, "build_object_store", build_object_store)
    monkeypatch.setattr(composition, "CorpusIngestor", corpus_ingestor)
    monkeypatch.setattr(composition, "VectorIndexRepository", vector_index_repository)
    monkeypatch.setattr(composition, "KnowledgeRepository", knowledge_repository)

    service = composition.build_corpus_workspace_service(settings, subject)

    create_session_factory.assert_called_once_with(settings.database_url)
    corpus_repository.assert_called_once_with(sessions)
    workspace_repository.assert_called_once_with(sessions)
    vector_index_repository.assert_called_once_with(sessions)
    knowledge_repository.assert_called_once_with(sessions)
    build_object_store.assert_called_once_with(settings)
    subject.runtime_settings.assert_called_once_with(settings)
    corpus_ingestor.assert_called_once_with(
        documents,
        runtime_settings,
        subject,
        object_store,
    )

    assert service.settings is settings
    assert service.subject is subject
    assert service.workspaces is workspaces
    assert service.documents is documents
    assert service.object_store is object_store
    assert service.ingestor is ingestor
    assert service.vector_indexes is vector_indexes
    assert service.knowledge is knowledge


def test_get_corpus_workspace_service_delegates_exactly_to_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = object()
    subject = object()
    expected_service = object()
    builder = Mock(return_value=expected_service)
    monkeypatch.setattr(dependencies, "build_corpus_workspace_service", builder)

    service = dependencies.get_corpus_workspace_service(settings, subject)

    assert service is expected_service
    builder.assert_called_once_with(settings, subject)
