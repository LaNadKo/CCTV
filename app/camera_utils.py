from typing import Union
from urllib.parse import quote, urlsplit, urlunsplit

from app import models


def _inject_credentials(url: str, username: str | None, password: str | None) -> str:
    if not username or not password or "://" not in url:
        return url
    parsed = urlsplit(url)
    if parsed.username or parsed.password:
        return url
    host = parsed.hostname or ""
    if not host:
        return url
    auth = quote(username, safe="") + ":" + quote(password, safe="") + "@" + host
    if parsed.port:
        auth += f":{parsed.port}"
    return urlunsplit((parsed.scheme, auth, parsed.path, parsed.query, parsed.fragment))


def resolve_source(cam: models.Camera) -> Union[int, str]:
    """Choose an OpenCV-friendly source from stored fields and camera endpoints."""
    endpoints = sorted(
        cam.endpoints or [],
        key=lambda item: (not bool(getattr(item, "is_primary", False)), getattr(item, "camera_endpoint_id", 0)),
    )
    for endpoint in endpoints:
        url = getattr(endpoint, "endpoint_url", None)
        if not url:
            continue
        return _inject_credentials(url, getattr(endpoint, "username", None), getattr(endpoint, "password_secret", None))

    if cam.stream_url:
        if cam.stream_url.startswith("local"):
            parts = cam.stream_url.split(":")
            if len(parts) == 1 or parts[1] == "":
                return 0
            try:
                return int(parts[1])
            except ValueError:
                return cam.stream_url
        return cam.stream_url
    if cam.ip_address:
        return cam.ip_address
    return 0  # fallback to default laptop webcam
