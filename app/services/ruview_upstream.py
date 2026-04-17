from __future__ import annotations

import time
from typing import Any

import httpx

from app.config import settings
from app.schemas.ruview import RuViewEndpointStatus, RuViewUpstreamStatus


def candidate_base_urls() -> list[str]:
    urls = []
    for raw in settings.ruview_upstream_urls.split(","):
        url = raw.strip().rstrip("/")
        if url:
            urls.append(url)
    return urls


async def _fetch_json(client: httpx.AsyncClient, url: str) -> dict[str, Any] | None:
    response = await client.get(url)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


async def get_ruview_upstream_status() -> RuViewUpstreamStatus:
    urls = candidate_base_urls()
    status = RuViewUpstreamStatus(
        enabled=settings.ruview_upstream_enabled,
        primary_url=urls[0] if urls else None,
    )
    if not settings.ruview_upstream_enabled:
        return status

    timeout = httpx.Timeout(settings.ruview_upstream_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for base_url in urls:
            started = time.perf_counter()
            endpoint = RuViewEndpointStatus(url=base_url, reachable=False)
            try:
                endpoint.health = await _fetch_json(client, f"{base_url}/health")
                endpoint.stream_status = await _fetch_json(client, f"{base_url}/api/v1/stream/status")
                endpoint.pose_stats = await _fetch_json(client, f"{base_url}/api/v1/pose/stats")
                endpoint.reachable = True
            except Exception as exc:
                endpoint.error = str(exc)
            endpoint.latency_ms = round((time.perf_counter() - started) * 1000, 1)
            status.endpoints.append(endpoint)
    return status
