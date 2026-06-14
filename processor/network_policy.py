from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlsplit, urlunsplit


_HOST_RE = re.compile(r"^[a-z0-9.-]+$", re.IGNORECASE)
_LOCAL_HOSTS = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}


def _is_allowed_camera_ip(value: str) -> bool:
    parsed_ip = ipaddress.ip_address(value)
    return not (
        parsed_ip.is_loopback
        or parsed_ip.is_unspecified
        or parsed_ip.is_multicast
        or parsed_ip.is_link_local
    )


def _validate_resolved_host_ips(host: str) -> None:
    try:
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Camera host cannot be resolved safely") from exc
    except OSError as exc:
        raise ValueError("Camera host cannot be resolved safely") from exc
    for item in addresses:
        sockaddr = item[4]
        if not sockaddr:
            continue
        try:
            address = str(sockaddr[0])
            if not _is_allowed_camera_ip(address):
                raise ValueError("Camera host resolves to a blocked address")
        except ValueError:
            raise


def _resolved_safe_host_ip(host: str) -> str | None:
    try:
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Camera host cannot be resolved safely") from exc
    except OSError as exc:
        raise ValueError("Camera host cannot be resolved safely") from exc
    for item in addresses:
        sockaddr = item[4]
        if not sockaddr:
            continue
        address = str(sockaddr[0])
        if _is_allowed_camera_ip(address):
            return address
    raise ValueError("Camera host resolves to a blocked address")


def _pin_url_host_to_ip(value: str, host: str) -> str:
    normalized = host.strip("[]").rstrip(".").lower()
    try:
        ipaddress.ip_address(normalized)
        return value
    except ValueError:
        pass
    pinned_ip = _resolved_safe_host_ip(normalized)
    parsed = urlsplit(value)
    userinfo = ""
    if "@" in parsed.netloc:
        userinfo = parsed.netloc.rsplit("@", 1)[0] + "@"
    host_text = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
    port_text = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit((parsed.scheme, f"{userinfo}{host_text}{port_text}", parsed.path, parsed.query, parsed.fragment))


def validate_camera_host(host: str | None) -> str | None:
    if host is None:
        return None
    value = host.strip()
    if not value:
        return None
    normalized = value.strip("[]").rstrip(".").lower()
    if normalized in _LOCAL_HOSTS or normalized.endswith(".localhost"):
        raise ValueError("Camera host must not point to localhost")
    try:
        parsed_ip = ipaddress.ip_address(normalized)
    except ValueError:
        if not _HOST_RE.fullmatch(normalized):
            raise ValueError("Camera host contains invalid characters")
        _validate_resolved_host_ips(normalized)
        return value
    if not _is_allowed_camera_ip(str(parsed_ip)):
        raise ValueError("Camera host is not allowed by network policy")
    return value


def validate_camera_url(url: str | None, allowed_schemes: set[str]) -> str | None:
    if url is None:
        return None
    value = url.strip()
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in allowed_schemes:
        raise ValueError("Camera URL scheme is not allowed")
    try:
        host = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Camera URL port is invalid") from exc
    if not host:
        raise ValueError("Camera URL host is required")
    validate_camera_host(host)
    return _pin_url_host_to_ip(value, host)


def validate_camera_stream_source(source: str | None) -> str | None:
    if source is None:
        return None
    value = source.strip()
    if not value:
        return None
    lowered = value.lower()
    if value.isdigit() or lowered == "local" or lowered.startswith("local:"):
        return value
    return validate_camera_url(value, {"rtsp", "rtsps", "http", "https"})


def validate_camera_endpoint_url(endpoint_kind: str, url: str | None) -> str | None:
    kind = endpoint_kind.strip().lower()
    if kind == "rtsp":
        return validate_camera_url(url, {"rtsp", "rtsps"})
    if kind in {"http", "onvif"}:
        return validate_camera_url(url, {"http", "https"})
    raise ValueError("Unknown camera endpoint kind")
