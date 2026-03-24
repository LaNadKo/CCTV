"""Helpers for processor-owned media proxying."""
from __future__ import annotations

import json
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app import models


PROCESSOR_MEDIA_SCHEME = "processor://"
DEFAULT_PROCESSOR_MEDIA_PORT = 8777


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
    if not proc.ip_address:
        raise RuntimeError("Processor IP is unknown")
    return f"http://{proc.ip_address}:{get_processor_media_port(proc)}"


def get_processor_media_headers(proc: models.Processor) -> dict[str, str]:
    headers: dict[str, str] = {}
    token = get_processor_media_token(proc)
    if token:
        headers["X-Processor-Media-Token"] = token
    return headers


async def get_processor_by_id(session: AsyncSession, processor_id: int) -> models.Processor | None:
    return await session.get(models.Processor, processor_id)
