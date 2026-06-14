from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any


class ScopedRequestBodyLimitMiddleware:
    def __init__(
        self,
        app,
        *,
        max_bytes: int,
        path_patterns: tuple[str, ...],
        methods: tuple[str, ...] = ("POST", "PUT", "PATCH"),
    ):
        self.app = app
        self.max_bytes = max(1, int(max_bytes))
        self.path_patterns = tuple(re.compile(pattern) for pattern in path_patterns)
        self.methods = frozenset(method.upper() for method in methods)

    def _matches(self, scope: dict[str, Any]) -> bool:
        if scope.get("type") != "http":
            return False
        if str(scope.get("method", "")).upper() not in self.methods:
            return False
        path = str(scope.get("path") or "")
        return any(pattern.fullmatch(path) for pattern in self.path_patterns)

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if not self._matches(scope):
            await self.app(scope, receive, send)
            return

        for raw_name, raw_value in scope.get("headers", []):
            if raw_name.lower() != b"content-length":
                continue
            try:
                if int(raw_value) > self.max_bytes:
                    await self._send_too_large(send)
                    return
            except ValueError:
                pass

        buffered_messages: list[dict[str, Any]] = []
        total = 0
        while True:
            message = await receive()
            buffered_messages.append(message)
            if message.get("type") != "http.request":
                break
            total += len(message.get("body", b""))
            if total > self.max_bytes:
                await self._send_too_large(send)
                return
            if not message.get("more_body", False):
                break

        index = 0

        async def replay_receive() -> dict[str, Any]:
            nonlocal index
            if index < len(buffered_messages):
                message = buffered_messages[index]
                index += 1
                return message
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _send_too_large(
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        body = json.dumps({"detail": "Processor metadata body is too large"}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
