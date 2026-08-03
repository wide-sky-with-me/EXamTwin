from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def upstream_http_error(code: str, message: str, error: Exception) -> HTTPException:
    """Keep provider/internal diagnostics in logs while returning a stable public error."""

    error_id = uuid4().hex[:12]
    logger.exception(
        "api_failure code=%s error_id=%s error_type=%s",
        code,
        error_id,
        type(error).__name__,
    )
    return HTTPException(
        status_code=502,
        detail=f"{message}（错误编号 {error_id}）",
        headers={"X-Error-Code": code, "X-Error-ID": error_id},
    )
