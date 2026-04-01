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


def resolve_source(assignment: dict) -> str | int | None:
    endpoints = assignment.get("endpoints", [])
    rtsp_candidates: list[tuple[int, str]] = []
    http_candidates: list[tuple[int, str]] = []
    for endpoint in endpoints:
        kind = endpoint.get("endpoint_kind")
        url = endpoint.get("endpoint_url")
        if not kind or not url:
            continue
        weight = 100 if endpoint.get("is_primary") else 0
        auth_url = _inject_credentials(url, endpoint.get("username"), endpoint.get("password_secret"))
        if kind == "rtsp":
            rtsp_candidates.append((weight, auth_url))
        elif kind == "http":
            http_candidates.append((weight, auth_url))
    if rtsp_candidates:
        rtsp_candidates.sort(reverse=True)
        return rtsp_candidates[0][1]
    if http_candidates:
        http_candidates.sort(reverse=True)
        return http_candidates[0][1]

    if assignment.get("stream_url"):
        src = assignment["stream_url"]
        if isinstance(src, str) and src.isdigit():
            return int(src)
        return src

    ip = assignment.get("ip_address")
    if ip:
        return f"rtsp://{ip}:554/stream"
    return None
