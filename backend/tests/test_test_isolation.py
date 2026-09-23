from __future__ import annotations

import os
import socket
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from dotenv import load_dotenv
from examtwin.platform.config import Settings
from examtwin.subjects import public as subjects
from sqlalchemy.exc import SQLAlchemyError

from backend.tests.conftest import pytest_collection_modifyitems


def test_unit_settings_do_not_use_developer_services_or_credentials() -> None:
    settings = Settings()
    assert settings.database_url == "postgresql://unit:unit@127.0.0.1:1/unit_tests"
    assert settings.object_store_backend == "local"
    assert settings.llm_base_url == "https://models.invalid/v1"
    assert settings.retrieval_base_url == "https://retrieval.invalid/v1"
    assert settings.llm_api_key is None
    assert settings.retrieval_api_key is None
    assert settings.mineru_token is None


def test_dependency_dotenv_loading_is_disabled(tmp_path: Path, monkeypatch) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("EXAMTWIN_TEST_DOTENV_LEAK=loaded\n", encoding="utf-8")
    monkeypatch.delenv("EXAMTWIN_TEST_DOTENV_LEAK", raising=False)
    assert load_dotenv(dotenv, override=True) is False
    assert "EXAMTWIN_TEST_DOTENV_LEAK" not in os.environ


@pytest.mark.parametrize("owner", ["module", "sync_class", "async_class"])
def test_uninjected_database_access_is_rejected(owner: str) -> None:
    owners = {
        "module": psycopg,
        "sync_class": psycopg.Connection,
        "async_class": psycopg.AsyncConnection,
    }
    with pytest.raises(AssertionError, match="inject a database fake"):
        owners[owner].connect(Settings().database_url)


@pytest.mark.parametrize("method", ["connect", "connect_ex"])
def test_ip_network_access_is_rejected(method: str) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(AssertionError, match="must not access the network"):
            getattr(sock, method)(("127.0.0.1", 8000))


def test_subject_resolver_keeps_missing_workspace_fail_closed() -> None:
    with pytest.raises(ValueError, match="科目工作区不存在"):
        subjects.subject_context(Settings(), "not-an-installed-workspace")


def test_subject_resolver_keeps_database_outage_fail_closed(monkeypatch) -> None:
    class UnavailableRepository:
        def __init__(self, _sessions):
            pass

        def resolve_subject(self, _selector):
            raise SQLAlchemyError("offline database fixture")

    monkeypatch.setattr(subjects, "WorkspaceRepository", UnavailableRepository)
    with pytest.raises(ValueError, match="科目目录暂不可用"):
        subjects.subject_context(Settings())


@pytest.mark.parametrize("collectonly, integration", [(False, False), (True, True)])
def test_unselected_integration_database_is_not_provisioned(
    monkeypatch, collectonly: bool, integration: bool
) -> None:
    monkeypatch.setenv("EXAMTWIN_TEST_DATABASE_URL", "postgresql://unit:unit@127.0.0.1:1/base")
    config = SimpleNamespace(option=SimpleNamespace(collectonly=collectonly))
    item = SimpleNamespace(get_closest_marker=lambda _name: integration)
    # The active psycopg guard would raise if collection touched any database.
    pytest_collection_modifyitems(config, [item])
    assert not hasattr(config, "_examtwin_test_database")
