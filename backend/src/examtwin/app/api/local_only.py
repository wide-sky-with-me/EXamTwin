from __future__ import annotations

import ipaddress
from collections.abc import Awaitable, Callable, Sequence
from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class LocalOnlyMiddleware:
    """Fail closed for non-loopback clients until a real auth boundary exists."""

    def __init__(self, app: ASGIApp, *, enabled: bool, allowed_origins: Sequence[str] = ()) -> None:
        self.app = app
        self.enabled = enabled
        self.allowed_origins = frozenset(allowed_origins)

    def _host_allowed(self, scope: Scope) -> bool:
        hosts = [
            value.decode("latin-1")
            for name, value in scope.get("headers", [])
            if name.lower() == b"host"
        ]
        if not hosts:
            return True
        if len(hosts) != 1:
            return False
        try:
            parsed = urlsplit("//" + hosts[0])
            hostname = parsed.hostname or ""
            _ = parsed.port  # Reject malformed ports as well as malformed hosts.
            if parsed.path or parsed.query or parsed.fragment or parsed.username is not None:
                return False
            client = scope.get("client")
            if hostname == "testserver" and client and client[0] == "testclient":
                return True
            if hostname == "localhost" or hostname in {
                urlsplit(origin).hostname for origin in self.allowed_origins
            }:
                return True
            return ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            return False

    def _origin_allowed(self, scope: Scope) -> bool:
        if not self._host_allowed(scope):
            return False
        origins = [
            value.decode("latin-1")
            for name, value in scope.get("headers", [])
            if name.lower() == b"origin"
        ]
        if not origins:
            return True  # Native local clients do not send a browser Origin.
        if len(origins) != 1:
            return False
        origin = origins[0]
        if origin in self.allowed_origins and origin != "null":
            return True
        # Preserve same-origin loopback API docs and local reverse proxies without
        # trusting arbitrary Host values (which would permit DNS rebinding).
        try:
            parsed = urlsplit(origin)
            hostname = parsed.hostname or ""
            local_host = hostname == "localhost" or ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            return False
        hosts = [
            value.decode("latin-1")
            for name, value in scope.get("headers", [])
            if name.lower() == b"host"
        ]
        scheme = {"ws": "http", "wss": "https"}.get(str(scope.get("scheme")), scope.get("scheme"))
        return (
            local_host
            and parsed.scheme in {"http", "https"}
            and parsed.scheme == scheme
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
            and parsed.username is None
            and parsed.password is None
            and hosts == [parsed.netloc]
        )

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
        origin_allowed = self._origin_allowed(scope) if allowed else True
        if allowed and origin_allowed:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send(
                {
                    "type": "websocket.close",
                    "code": 4403,
                    "reason": "local access only" if origin_allowed else "untrusted browser origin",
                }
            )
            return
        response = JSONResponse(
            status_code=403,
            content={
                "detail": "当前单用户部署仅允许本机访问"
                if origin_allowed
                else "不允许此网页来源访问本机服务"
            },
        )
        await response(scope, receive, send)
