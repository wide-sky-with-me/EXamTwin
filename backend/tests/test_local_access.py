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
