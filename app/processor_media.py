"""Helpers for processor-owned media proxying."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app import models


PROCESSOR_MEDIA_SCHEME = "processor://"
DEFAULT_PROCESSOR_MEDIA_PORT = 8777
PROCESSOR_HEARTBEAT_GRACE_SECONDS = 90


def build_processor_file_path(processor_id: int, relative_path: str) -> str:
    return f"{PROCESSOR_MEDIA_SCHEME}{processor_id}/{relative_path.lstrip('/')}"


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
        return int(capabilities.get("media_port") or DEFAULT_PROCESSOR_MEDIA_PORT)
    except (TypeError, ValueError):
        return DEFAULT_PROCESSOR_MEDIA_PORT


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
    for host in hosts:
        if not host:
            continue
        url = f"http://{host}:{port}"
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


async def get_processor_by_id(session: AsyncSession, processor_id: int) -> models.Processor | None:
    return await session.get(models.Processor, processor_id)
