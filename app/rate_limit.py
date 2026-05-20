from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque

from fastapi import HTTPException, Request, status


_attempts: dict[str, Deque[float]] = defaultdict(deque)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def check_rate_limit(
    request: Request,
    bucket: str,
    *,
    attempts: int,
    window_seconds: int,
    detail: str = "Too many requests",
) -> None:
    now = time.monotonic()
    key = f"{bucket}:{client_ip(request)}"
    queue = _attempts[key]
    while queue and now - queue[0] > window_seconds:
        queue.popleft()
    if len(queue) >= attempts:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            headers={"Retry-After": str(window_seconds)},
        )
    queue.append(now)

    # Keep the in-memory limiter bounded for long-running demo servers.
    if len(_attempts) > 4096:
        expired_keys = [item_key for item_key, item_queue in _attempts.items() if not item_queue or now - item_queue[-1] > window_seconds]
        for item_key in expired_keys[:1024]:
            _attempts.pop(item_key, None)
