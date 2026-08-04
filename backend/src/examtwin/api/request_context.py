from __future__ import annotations

import logging
import re
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from starlette.types import Message, Receive, Scope, Send

from examtwin.observability import request_id_context

ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,63}$")
logger = logging.getLogger(__name__)


def _request_id(scope: Scope) -> str:
    headers = {key.lower(): value for key, value in scope.get("headers", [])}
    raw_value = headers.get(b"x-request-id", b"")
    try:
        candidate = raw_value.decode("ascii")
    except UnicodeDecodeError:
        candidate = ""
    return candidate if REQUEST_ID_PATTERN.fullmatch(candidate) else uuid4().hex


class RequestContextMiddleware:
    """Attach a bounded correlation ID and emit one structured HTTP completion event."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id(scope)
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_context.set(request_id)
        started = time.monotonic()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = list(message.get("headers", []))
                if not any(key.lower() == b"x-request-id" for key, _value in headers):
                    headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            logger.info(
                "http_request_completed",
                extra={
                    "event": "http_request_completed",
                    "method": scope.get("method", ""),
                    "path": scope.get("path", ""),
                    "status_code": status_code,
                    "duration_ms": round((time.monotonic() - started) * 1000, 2),
                },
            )
            request_id_context.reset(token)
