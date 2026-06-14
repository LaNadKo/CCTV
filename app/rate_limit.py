from __future__ import annotations

import hashlib
import ipaddress
import time
from collections import defaultdict, deque
from typing import Deque

from fastapi import HTTPException, Request, status

from app.config import settings


_attempts: dict[str, Deque[float]] = defaultdict(deque)


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client and request.client.host else None
    if not peer:
        return "unknown"
    try:
        peer_ip = ipaddress.ip_address(peer)
        trusted = any(
            peer_ip in ipaddress.ip_network(value, strict=False)
            for value in settings.trusted_proxy_networks
        )
    except ValueError:
        trusted = False
    if trusted:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            forwarded_chain = [item.strip() for item in forwarded.split(",") if item.strip()]
            trusted_networks = [
                ipaddress.ip_network(value, strict=False)
                for value in settings.trusted_proxy_networks
            ]
            for candidate in reversed(forwarded_chain):
                try:
                    candidate_ip = ipaddress.ip_address(candidate)
                except ValueError:
                    continue
                if not any(candidate_ip in network for network in trusted_networks):
                    return str(candidate_ip)
    if peer:
        return peer
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
    bucket_digest = hashlib.sha256(bucket.encode("utf-8", errors="ignore")).hexdigest()
    key = f"{bucket_digest}:{client_ip(request)}"
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
        expired_keys = [
            item_key
            for item_key, item_queue in _attempts.items()
            if not item_queue or now - item_queue[-1] > window_seconds
        ]
        for item_key in expired_keys[:1024]:
            _attempts.pop(item_key, None)
        if len(_attempts) > 4096:
            oldest_keys = sorted(
                _attempts,
                key=lambda item_key: _attempts[item_key][-1] if _attempts[item_key] else float("-inf"),
            )
            for item_key in oldest_keys[: len(_attempts) - 4096]:
                _attempts.pop(item_key, None)
