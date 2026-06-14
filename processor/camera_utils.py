"""Camera source resolution for OpenCV."""
from __future__ import annotations

import logging
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from processor.network_policy import validate_camera_endpoint_url, validate_camera_host, validate_camera_stream_source

logger = logging.getLogger(__name__)
_SENSITIVE_QUERY_NAMES = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "key",
    "password",
    "secret",
    "token",
}


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


def redact_source(value: str | int | None) -> str | int | None:
    if not isinstance(value, str) or "://" not in value:
        return value
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "<invalid-url>"
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    try:
        port = parsed.port
    except ValueError:
        return "<invalid-url>"
    if port is not None:
        netloc = f"{netloc}:{port}"
    if parsed.username is not None:
        netloc = f"***:***@{netloc}"
    query = urlencode(
        [
            (name, "***" if name.lower() in _SENSITIVE_QUERY_NAMES else item)
            for name, item in parse_qsl(parsed.query, keep_blank_values=True)
        ]
    )
    return urlunsplit((parsed.scheme, netloc, parsed.path, query, ""))


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
        try:
            url = validate_camera_endpoint_url(str(kind), str(url))
        except ValueError:
            logger.warning("Skipping camera endpoint blocked by network policy: kind=%s", kind)
            continue
        if not url:
            continue
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
        try:
            src = validate_camera_stream_source(src if isinstance(src, str) else str(src))
        except ValueError:
            logger.warning("Skipping camera stream_url blocked by network policy")
            src = None
        if isinstance(src, str) and src.isdigit():
            _append_unique(candidates, int(src))
        elif isinstance(src, str) and src.lower().startswith("rtsp://"):
            for url in _with_rtsp_fallbacks(src):
                _append_unique(candidates, url)
        elif src:
            _append_unique(candidates, src)

    ip = assignment.get("ip_address")
    if ip:
        try:
            ip = validate_camera_host(str(ip))
        except ValueError:
            logger.warning("Skipping camera ip_address blocked by network policy")
            ip = None
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
