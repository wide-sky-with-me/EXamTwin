from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest
from examtwin.platform.config import Settings, get_settings
from psycopg import sql
from sqlalchemy.engine import make_url

# Unit tests must never inherit local provider credentials or optional capabilities.
Settings.model_config["env_file"] = None
for name, value in {
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
}.items():
    os.environ.setdefault(name, value)


def pytest_configure(config: pytest.Config) -> None:
    """Give every integration run a fresh database instead of sharing stale schema state."""
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
def clear_settings_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    # Tests opt into one explicit bootstrap context; production must configure its own.
    monkeypatch.setenv("SUBJECT_PACK", "oxfordaqa-mathematics-9660")
    monkeypatch.setenv("QDRANT_COLLECTION", "examtwin_9660")
    monkeypatch.setenv("QDRANT_COLLECTION_ALIAS", "examtwin_9660_live")
    monkeypatch.setenv("CORPUS_ROOT", "data/牛津AQA/数学")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
