"""Read-only client for the official RuView sensing server."""
from __future__ import annotations

from typing import Any

import httpx

from app.config import settings
from app.schemas.ruview import RuViewUpstreamStatus


def _candidate_base_urls() -> list[str]:
    urls = [url.strip().rstrip("/") for url in settings.ruview_upstream_urls.split(",")]
    return [url for url in urls if url]


def _format_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{exc.response.status_code} from {exc.request.url}"
    if isinstance(exc, httpx.RequestError):
        return f"{exc.__class__.__name__}: {exc.request.url}"
    return str(exc)


async def _fetch_json(client: httpx.AsyncClient, base_url: str, path: str) -> dict[str, Any]:
    response = await client.get(f"{base_url}/{path.lstrip('/')}")
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {"value": data}


async def _fetch_optional(client: httpx.AsyncClient, base_url: str, path: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return await _fetch_json(client, base_url, path), None
    except (httpx.HTTPError, ValueError) as exc:
        return None, _format_error(exc)


async def get_ruview_upstream_status() -> RuViewUpstreamStatus:
    if not settings.ruview_upstream_enabled:
        return RuViewUpstreamStatus(enabled=False, reachable=False, error="RuView upstream is disabled")

    candidates = _candidate_base_urls()
    if not candidates:
        return RuViewUpstreamStatus(enabled=True, reachable=False, error="No RuView upstream URLs configured")

    timeout_seconds = max(0.2, float(settings.ruview_upstream_timeout_seconds))
    timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 0.5))
    last_error: str | None = None

    async with httpx.AsyncClient(timeout=timeout) as client:
        for base_url in candidates:
            try:
                health = await _fetch_json(client, base_url, "/health")
            except (httpx.HTTPError, ValueError) as exc:
                last_error = _format_error(exc)
                continue

            stream_status, stream_error = await _fetch_optional(client, base_url, "/api/v1/stream/status")
            pose_current, pose_error = await _fetch_optional(client, base_url, "/api/v1/pose/current")
            pose_stats, stats_error = await _fetch_optional(client, base_url, "/api/v1/pose/stats")
            partial_errors = [error for error in (stream_error, pose_error, stats_error) if error]

            return RuViewUpstreamStatus(
                enabled=True,
                reachable=True,
                base_url=base_url,
                health=health,
                stream_status=stream_status,
                pose_current=pose_current,
                pose_stats=pose_stats,
                error="; ".join(partial_errors) if partial_errors else None,
            )

    return RuViewUpstreamStatus(enabled=True, reachable=False, base_url=candidates[0], error=last_error)
