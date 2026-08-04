from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from examtwin.observability import safe_exception_extra

logger = logging.getLogger(__name__)
ResultT = TypeVar("ResultT")


def api_http_error(
    code: str,
    message: str,
    error: Exception,
    *,
    status_code: int,
) -> HTTPException:
    """Keep provider/internal diagnostics in logs while returning a stable public error."""

    error_id = uuid4().hex[:12]
    logger.error(
        "api_failure",
        extra={
            "event": "api_failure",
            "error_code": code,
            "error_id": error_id,
            **safe_exception_extra(error),
        },
    )
    return HTTPException(
        status_code=status_code,
        detail=f"{message}（错误编号 {error_id}）",
        headers={"X-Error-Code": code, "X-Error-ID": error_id},
    )


def upstream_http_error(code: str, message: str, error: Exception) -> HTTPException:
    return api_http_error(code, message, error, status_code=502)


def guarded_api_call(
    operation: Callable[[], ResultT],
    *,
    code: str,
    message: str,
    status_code: int = 500,
) -> ResultT:
    try:
        return operation()
    except HTTPException:
        raise
    except Exception as error:
        raise api_http_error(code, message, error, status_code=status_code) from error


async def unhandled_api_error(_request: Request, error: Exception) -> JSONResponse:
    failure = api_http_error(
        "INTERNAL_SERVER_ERROR",
        "服务内部错误，请稍后重试",
        error,
        status_code=500,
    )
    headers = dict(failure.headers or {})
    request_id = getattr(_request.state, "request_id", None)
    if request_id:
        headers["X-Request-ID"] = request_id
    return JSONResponse(
        status_code=failure.status_code,
        content={"detail": failure.detail},
        headers=headers,
    )
