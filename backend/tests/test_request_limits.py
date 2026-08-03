from __future__ import annotations

import json

import pytest
from examtwin.api.request_limits import UploadBodyLimitMiddleware
from starlette.types import Message, Receive, Scope, Send


@pytest.mark.asyncio
async def test_upload_body_limit_rejects_declared_and_streamed_oversize_requests() -> None:
    app_calls = 0

    async def consume_body(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal app_calls
        del scope
        app_calls += 1
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = UploadBodyLimitMiddleware(
        consume_body,
        upload_path="/api/v1/papers/answer",
        max_body_bytes=8,
    )

    async def run(headers: list[tuple[bytes, bytes]], bodies: list[bytes]) -> list[Message]:
        messages: list[Message] = [
            {
                "type": "http.request",
                "body": body,
                "more_body": index < len(bodies) - 1,
            }
            for index, body in enumerate(bodies)
        ]
        sent: list[Message] = []

        async def receive() -> Message:
            return messages.pop(0)

        async def send(message: Message) -> None:
            sent.append(message)

        await middleware(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/v1/papers/answer",
                "headers": headers,
            },
            receive,
            send,
        )
        return sent

    declared = await run([(b"content-length", b"9")], [b"unused"])
    streamed = await run([], [b"12345", b"6789"])

    assert app_calls == 1
    assert declared[0]["status"] == 413
    assert streamed[0]["status"] == 413
    assert "容量限制" in json.loads(streamed[1]["body"])["detail"]
