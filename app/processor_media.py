"""Helpers for processor-owned media proxying."""
from __future__ import annotations

import json
import ipaddress
import re
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Optional
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.network_policy import validate_camera_url
from cctv_ai.media_auth import issue_scoped_media_token


PROCESSOR_MEDIA_SCHEME = "processor://"
DEFAULT_PROCESSOR_MEDIA_PORT = 8777
PROCESSOR_HEARTBEAT_GRACE_SECONDS = 90
_MEDIA_HOST_RE = re.compile(r"^[A-Za-z0-9_.-]{1,253}$")


def build_processor_file_path(processor_id: int, relative_path: str) -> str:
    return f"{PROCESSOR_MEDIA_SCHEME}{processor_id}/{safe_processor_relative_path(relative_path)}"


def safe_processor_relative_path(value: str) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    if not raw or "\x00" in raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise ValueError("Invalid processor media path")
    parts = PurePosixPath(raw).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Invalid processor media path")
    return "/".join(parts)


def parse_processor_file_path(file_path: str) -> tuple[int, str] | None:
    if not file_path.startswith(PROCESSOR_MEDIA_SCHEME):
        return None
    rest = file_path[len(PROCESSOR_MEDIA_SCHEME) :]
    if "/" not in rest:
        return None
    processor_raw, relative_path = rest.split("/", 1)
    try:
        processor_id = int(processor_raw)
    except ValueError:
        return None
    if processor_id <= 0:
        return None
    try:
        relative_path = safe_processor_relative_path(relative_path)
    except ValueError:
        return None
    return processor_id, relative_path


def get_processor_capabilities(proc: models.Processor) -> dict:
    if not proc.capabilities:
        return {}
    try:
        return json.loads(proc.capabilities)
    except (json.JSONDecodeError, TypeError):
        return {}


def effective_processor_status(proc: models.Processor) -> str:
    status = (proc.status or "offline").lower()
    if status != "online":
        return status
    if proc.last_heartbeat is None:
        return "offline"
    if proc.last_heartbeat < datetime.utcnow() - timedelta(seconds=PROCESSOR_HEARTBEAT_GRACE_SECONDS):
        return "offline"
    return "online"


def is_processor_effectively_online(proc: models.Processor) -> bool:
    return effective_processor_status(proc) == "online"


def get_processor_media_port(proc: models.Processor) -> int:
    capabilities = get_processor_capabilities(proc)
    try:
        port = int(capabilities.get("media_port") or DEFAULT_PROCESSOR_MEDIA_PORT)
    except (TypeError, ValueError):
        return DEFAULT_PROCESSOR_MEDIA_PORT
    return port if 1 <= port <= 65535 else DEFAULT_PROCESSOR_MEDIA_PORT


def _format_url_host(host: str) -> str:
    try:
        parsed_ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return host
    return f"[{parsed_ip}]" if parsed_ip.version == 6 else str(parsed_ip)


def _safe_processor_media_host(value: object) -> str | None:
    host = str(value or "").strip()
    if not host or not _MEDIA_HOST_RE.fullmatch(host):
        return None
    labels = host.split(".")
    if any(not label or label.startswith("-") or label.endswith("-") for label in labels):
        return None
    try:
        pinned = validate_camera_url(f"http://{host}:1", {"http"})
    except ValueError:
        return None
    if not pinned:
        return None
    parsed = urlsplit(pinned)
    return parsed.hostname


def get_processor_media_token(proc: models.Processor) -> Optional[str]:
    capabilities = get_processor_capabilities(proc)
    token = capabilities.get("media_token")
    return str(token) if token else None


def get_processor_media_base_url(proc: models.Processor) -> str:
    urls = get_processor_media_base_urls(proc)
    if not urls:
        raise RuntimeError("Processor IP is unknown")
    return urls[0]


def get_processor_media_base_urls(proc: models.Processor) -> list[str]:
    capabilities = get_processor_capabilities(proc)
    port = get_processor_media_port(proc)
    hosts = [
        capabilities.get("advertised_ip"),
        proc.ip_address,
        "host.docker.internal",
    ]
    urls: list[str] = []
    seen: set[str] = set()
    for raw_host in hosts:
        host = _safe_processor_media_host(raw_host)
        if host is None:
            continue
        url = f"http://{_format_url_host(host)}:{port}"
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def get_processor_media_headers(proc: models.Processor) -> dict[str, str]:
    headers: dict[str, str] = {}
    token = get_processor_media_token(proc)
    if token:
        headers["X-Processor-Media-Token"] = token
    return headers


def get_processor_direct_media_headers(
    proc: models.Processor,
    *,
    path: str,
) -> dict[str, str]:
    token = get_processor_media_token(proc)
    if not token:
        return {}
    return {
        "X-Processor-Media-Token": issue_scoped_media_token(
            token,
            path,
        )
    }


async def get_processor_by_id(session: AsyncSession, processor_id: int) -> models.Processor | None:
    return await session.get(models.Processor, processor_id)
