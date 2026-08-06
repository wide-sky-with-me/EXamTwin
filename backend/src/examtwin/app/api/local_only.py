from __future__ import annotations

import ipaddress
from collections.abc import Awaitable, Callable

from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class LocalOnlyMiddleware:
    """Fail closed for non-loopback clients until a real auth boundary exists."""

    def __init__(self, app: ASGIApp, *, enabled: bool) -> None:
        self.app = app
        self.enabled = enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.enabled or scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        host = str(client[0]) if client else ""
        try:
            allowed = ipaddress.ip_address(host).is_loopback
        except ValueError:
            allowed = host == "testclient"
        if allowed:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4403, "reason": "local access only"})
            return
        response = JSONResponse(
            status_code=403,
            content={"detail": "当前单用户部署仅允许本机访问"},
        )
        await response(scope, receive, send)
