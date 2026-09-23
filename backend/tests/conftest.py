from __future__ import annotations

import os
import socket
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from examtwin.platform.config import Settings, get_settings
from psycopg import sql
from sqlalchemy.engine import make_url

# LiteLLM imports call load_dotenv independently of Pydantic Settings. Disable
# that path before collection imports, or local S3/model credentials leak back in.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
# Tests must not inherit developer credentials, endpoints or optional capabilities.
# Explicit Settings(_env_file=...) remains available to configuration contract tests.
Settings.model_config["env_file"] = None
# Explicit infrastructure endpoints remain supported for integration runs only.
INTEGRATION_SERVICE_ENVIRONMENT = {
    name: os.environ[name] for name in ("QDRANT_URL", "QDRANT_API_KEY") if name in os.environ
}
for name in tuple(os.environ):
    if name.lower() in Settings.model_fields:
        os.environ.pop(name)
TEST_ENVIRONMENT = {
    "DATABASE_URL": "postgresql://unit:unit@127.0.0.1:1/unit_tests",
    "SUBJECT_PACK": "oxfordaqa-mathematics-9660",
    "QDRANT_COLLECTION": "examtwin_9660",
    "QDRANT_COLLECTION_ALIAS": "examtwin_9660_live",
    "CORPUS_ROOT": "data/牛津AQA/数学",
    "LITELLM_PROVIDER": "openai",
    "LLM_BASE_URL": "https://models.invalid/v1",
    "LLM_MODEL": "test-main-model",
    "KNOWLEDGE_DIFFICULTY_MODEL": "test-difficulty-model",
    "KNOWLEDGE_GRAPH_MODEL": "test-graph-model",
    "GRADING_MODEL": "test-grading-model",
    "PAPER_SPLIT_MODEL": "test-split-model",
    "PAPER_VISION_MODEL": "test-vision-model",
    "IMAGE_GENERATION_MODEL": "test-image-model",
    "RETRIEVAL_BASE_URL": "https://retrieval.invalid/v1",
    "EMBEDDING_MODEL": "test-embedding-model",
    "RERANK_MODEL": "test-rerank-model",
}
os.environ.update(TEST_ENVIRONMENT)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Provision an isolated database only when selected tests actually require it."""
    if config.option.collectonly or not any(
        item.get_closest_marker("integration") for item in items
    ):
        return
    configured_url = os.environ.get("EXAMTWIN_TEST_DATABASE_URL")
    if not configured_url:
        return
    base_url = make_url(configured_url)
    base_name = (base_url.database or "examtwin_test")[:36]
    database_name = f"{base_name}_{os.getpid()}_{uuid4().hex[:8]}"
    admin_url = base_url.set(database="postgres")
    with psycopg.connect(admin_url.render_as_string(hide_password=False), autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    temporary_url = base_url.set(database=database_name).render_as_string(hide_password=False)
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["EXAMTWIN_TEST_DATABASE_URL"] = temporary_url
    os.environ["DATABASE_URL"] = temporary_url
    config.__dict__["_examtwin_test_database"] = (
        admin_url,
        database_name,
        previous_database_url,
    )


def pytest_unconfigure(config: pytest.Config) -> None:
    owned = getattr(config, "_examtwin_test_database", None)
    if owned is None:
        return
    admin_url, database_name, previous_database_url = owned
    with psycopg.connect(admin_url.render_as_string(hide_password=False), autocommit=True) as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (database_name,),
        )
        conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))
    if previous_database_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous_database_url


@pytest.fixture(autouse=True)
def clear_settings_cache(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    # Some contract/export tests seed os.environ directly. Reset every Settings
    # input per test, not just once at import, so ordering cannot leak configuration.
    integration = bool(request.node.get_closest_marker("integration"))
    for name in tuple(os.environ):
        if name.lower() in Settings.model_fields:
            if integration and name.upper() == "DATABASE_URL":
                continue  # The collection hook owns the disposable integration DB.
            monkeypatch.delenv(name)
    for name, value in TEST_ENVIRONMENT.items():
        if not (integration and name == "DATABASE_URL"):
            monkeypatch.setenv(name, value)
    if integration:
        for name, value in INTEGRATION_SERVICE_ENVIRONMENT.items():
            monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def isolated_unit_services(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    clear_settings_cache: None,
) -> None:
    """Unit tests use declared workspace rows, never a running developer service.

    Patch the persistence input, not subject_context: selection, capability validation
    and retrieval binding still run through the real production resolver. Tests of
    missing/failed/custom repositories can override this default boundary themselves.
    """
    if request.node.get_closest_marker("integration"):
        return

    from examtwin.subjects import public as subjects
    from examtwin.subjects.packages import subject_package_registry

    monkeypatch.setenv("DATABASE_URL", "postgresql://unit:unit@127.0.0.1:1/unit_tests")
    monkeypatch.setenv("OBJECT_STORE_LOCAL_ROOT", str(tmp_path / "objects"))

    def reject_database(*_args, **_kwargs):
        raise AssertionError("Non-integration tests must inject a database fake")

    monkeypatch.setattr(psycopg, "connect", reject_database)
    monkeypatch.setattr(psycopg.Connection, "connect", reject_database)
    monkeypatch.setattr(psycopg.AsyncConnection, "connect", reject_database)

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def guarded_connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError(f"Non-integration tests must not access the network: {address}")
        return original_connect(sock, address)

    def guarded_connect_ex(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError(f"Non-integration tests must not access the network: {address}")
        return original_connect_ex(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)

    class UnitWorkspaceRepository:
        def __init__(self, _sessions):
            self.rows = [
                {
                    "id": package.pack.id,
                    "subject_code": package.pack.subject_code,
                    "title": package.pack.title,
                    "board_name": package.pack.board.name,
                    "capability_profile_id": package.pack.id,
                    "active_graph_version_id": None,
                    "knowledge_bases": [],
                }
                for package in subject_package_registry().all()
            ]

        def resolve_subject(self, selector):
            return next(
                (
                    deepcopy(row)
                    for row in self.rows
                    if selector in (row["id"], row["subject_code"])
                ),
                None,
            )

        def list_subjects(self):
            return deepcopy(self.rows)

    monkeypatch.setattr(subjects, "WorkspaceRepository", UnitWorkspaceRepository)
