"""Camera source resolution for OpenCV."""
from __future__ import annotations

import logging
from urllib.parse import quote

logger = logging.getLogger(__name__)


def _inject_credentials(url: str, username: str | None, password: str | None) -> str:
    if not username or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if "@" in rest:
        return url
    host_part, sep, path_part = rest.partition("/")
    user = quote(username, safe="")
    pwd = quote(password or "", safe="")
    auth_host = f"{user}:{pwd}@{host_part}"
    return f"{scheme}://{auth_host}{sep}{path_part}"


def _append_unique(items: list[str | int], value: str | int) -> None:
    if value not in items:
        items.append(value)


def _with_rtsp_fallbacks(url: str) -> list[str]:
    values = [url]
    lowered = url.lower()
    if lowered.endswith("/stream1"):
        values.append(url[:-1] + "2")
    elif lowered.endswith("/stream2"):
        values.append(url[:-1] + "1")
    return values


def source_candidates(assignment: dict) -> list[str | int]:
    endpoints = assignment.get("endpoints", [])
    rtsp_candidates: list[tuple[int, list[str]]] = []
    http_candidates: list[tuple[int, str]] = []
    for endpoint in endpoints:
        kind = endpoint.get("endpoint_kind")
        url = endpoint.get("endpoint_url")
        if not kind or not url:
            continue
        weight = 100 if endpoint.get("is_primary") else 0
        auth_url = _inject_credentials(url, endpoint.get("username"), endpoint.get("password_secret"))
        if kind == "rtsp":
            rtsp_candidates.append((weight, _with_rtsp_fallbacks(auth_url)))
        elif kind == "http":
            http_candidates.append((weight, auth_url))

    candidates: list[str | int] = []
    if rtsp_candidates:
        rtsp_candidates.sort(reverse=True)
        for _weight, urls in rtsp_candidates:
            for url in urls:
                _append_unique(candidates, url)
    if http_candidates:
        http_candidates.sort(reverse=True)
        for _weight, url in http_candidates:
            _append_unique(candidates, url)

    if assignment.get("stream_url"):
        src = assignment["stream_url"]
        if isinstance(src, str) and src.isdigit():
            _append_unique(candidates, int(src))
        elif isinstance(src, str) and src.lower().startswith("rtsp://"):
            for url in _with_rtsp_fallbacks(src):
                _append_unique(candidates, url)
        else:
            _append_unique(candidates, src)

    ip = assignment.get("ip_address")
    if ip:
        for url in (
            f"rtsp://{ip}:554/stream",
            f"rtsp://{ip}:554/stream1",
            f"rtsp://{ip}:554/stream2",
        ):
            _append_unique(candidates, url)
    return candidates


def resolve_source(assignment: dict) -> str | int | None:
    candidates = source_candidates(assignment)
    return candidates[0] if candidates else None
