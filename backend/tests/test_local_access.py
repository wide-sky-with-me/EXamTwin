from __future__ import annotations

import json

import pytest
from examtwin.app.api.local_only import LocalOnlyMiddleware


@pytest.mark.asyncio
async def test_local_only_middleware_rejects_remote_http_and_websocket_clients() -> None:
    async def unreachable(_scope: object, _receive: object, _send: object) -> None:
        raise AssertionError("remote request reached the application")

    async def receive() -> dict[str, object]:
        return {"type": "http.request"}

    messages: list[dict[str, object]] = []

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    middleware = LocalOnlyMiddleware(unreachable, enabled=True)  # type: ignore[arg-type]
    await middleware(
        {"type": "http", "client": ("192.0.2.10", 1234)},  # type: ignore[arg-type]
        receive,  # type: ignore[arg-type]
        send,  # type: ignore[arg-type]
    )
    assert messages[0]["status"] == 403
    assert "仅允许本机" in json.loads(messages[1]["body"])["detail"]  # type: ignore[arg-type]

    messages.clear()
    await middleware(
        {"type": "websocket", "client": ("192.0.2.10", 1234)},  # type: ignore[arg-type]
        receive,  # type: ignore[arg-type]
        send,  # type: ignore[arg-type]
    )
    assert messages == [{"type": "websocket.close", "code": 4403, "reason": "local access only"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["http", "websocket"])
@pytest.mark.parametrize(
    ("origin", "host", "expected_allowed"),
    [
        (None, "localhost:8000", True),
        (None, "rebinding.example:8000", False),
        ("http://localhost:5173", "localhost:8000", True),
        ("http://localhost:8000", "localhost:8000", True),
        ("http://127.0.0.1:8000", "127.0.0.1:8000", True),
        ("http://[::1]:8000", "[::1]:8000", True),
        ("http://localhost:5173", "rebinding.example:8000", False),
        ("https://untrusted.example", "localhost:8000", False),
        ("http://rebinding.example:8000", "rebinding.example:8000", False),
        ("http://127.0.0.1:9000", "127.0.0.1:8000", False),
        ("null", "localhost:8000", False),
        ("", "localhost:8000", False),
    ],
)
async def test_local_browser_origins_are_checked_before_application(
    protocol: str, origin: str | None, host: str, expected_allowed: bool
) -> None:
    from starlette.types import Message, Receive, Scope, Send

    called = False
    sent: list[Message] = []

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal called
        called = True

    async def receive() -> Message:
        return {"type": "http.request", "body": b""}

    async def send(message: Message) -> None:
        sent.append(message)

    headers = [(b"host", host.encode())]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    middleware = LocalOnlyMiddleware(
        application, enabled=True, allowed_origins=["http://localhost:5173"]
    )
    await middleware(
        {
            "type": protocol,
            "scheme": "ws" if protocol == "websocket" else "http",
            "client": ("127.0.0.1", 1234),
            "method": "POST",
            "headers": headers,
        },
        receive,
        send,
    )
    assert called is expected_allowed
    if not expected_allowed:
        assert sent[0].get("status", sent[0].get("code")) == (
            4403 if protocol == "websocket" else 403
        )
