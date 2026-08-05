import logging
import os

import pytest
from examtwin.api.errors import unhandled_api_error
from examtwin.api.request_context import RequestContextMiddleware
from examtwin.observability import JsonLogFormatter, configure_logging
from examtwin.persistence.migrations import upgrade_database
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _failing_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.add_exception_handler(Exception, unhandled_api_error)

    @app.get("/explode")
    def explode() -> None:
        raise RuntimeError("provider-token-must-not-leak")

    return app


def test_request_id_is_preserved_while_internal_error_details_are_hidden() -> None:
    request_id = "request-12345678"
    with TestClient(_failing_app(), raise_server_exceptions=False) as client:
        response = client.get("/explode", headers={"X-Request-ID": request_id})

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == request_id
    assert response.headers["X-Error-Code"] == "INTERNAL_SERVER_ERROR"
    assert "provider-token" not in response.text
    assert "错误编号" in response.json()["detail"]


def test_invalid_request_id_is_replaced_with_a_bounded_server_value() -> None:
    with TestClient(_failing_app(), raise_server_exceptions=False) as client:
        response = client.get("/explode", headers={"X-Request-ID": "bad id"})

    generated = response.headers["X-Request-ID"]
    assert generated != "bad id"
    assert len(generated) == 32


@pytest.mark.integration
def test_embedded_migration_preserves_structured_logging() -> None:
    database_url = os.environ.get("EXAMTWIN_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("EXAMTWIN_TEST_DATABASE_URL is required")

    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    try:
        configure_logging()
        structured_handler = root.handlers[0]

        upgrade_database(database_url)

        assert root.handlers == [structured_handler]
        assert isinstance(structured_handler.formatter, JsonLogFormatter)
    finally:
        root.handlers[:] = original_handlers
        root.setLevel(original_level)
