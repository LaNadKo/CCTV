"""Camera source resolution for OpenCV."""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


def resolve_source(assignment: dict) -> str | int | None:
    if assignment.get("stream_url"):
        src = assignment["stream_url"]
        if src.isdigit():
            return int(src)
        return src
    endpoints = assignment.get("endpoints", [])
    for ep in endpoints:
        if ep.get("endpoint_kind") == "rtsp":
            url = ep["endpoint_url"]
            if ep.get("username"):
                from urllib.parse import urlparse, urlunparse
                parsed = urlparse(url)
                url = urlunparse(parsed._replace(netloc=f"{ep['username']}:{ep.get('password_secret', '')}@{parsed.hostname}:{parsed.port or 554}"))
            return url
    for ep in endpoints:
        if ep.get("endpoint_kind") == "http":
            return ep["endpoint_url"]
    ip = assignment.get("ip_address")
    if ip:
        return f"rtsp://{ip}:554/stream"
    return None
