from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.config import settings

BACKEND_RECORDINGS_STORAGE_NAME = "Backend Recordings"


def recordings_root() -> Path:
    root = Path(settings.recordings_path or "recordings")
    if not root.is_absolute():
        root = Path.cwd() / root
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def recording_local_path(file_path: str | None) -> Path | None:
    if not file_path or file_path.startswith("processor://"):
        return None
    path = Path(file_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    try:
        path.relative_to(recordings_root())
    except ValueError:
        return None
    return path if path.is_file() else None


def safe_recording_relative_path(
    *,
    camera_id: int,
    started_at: datetime,
    source_path: str | None,
) -> str:
    filename = _safe_segment(Path(str(source_path or "")).name)
    if not filename or filename in {".", ".."}:
        filename = f"recording_{started_at.strftime('%Y%m%d_%H%M%S')}.mp4"
    if not Path(filename).suffix:
        filename = f"{filename}.mp4"
    return "/".join(
        [
            f"camera_{camera_id}",
            started_at.strftime("%Y-%m-%d"),
            started_at.strftime("%H"),
            filename,
        ]
    )


def backend_recording_path(relative_path: str) -> Path:
    root = recordings_root()
    clean = _safe_relative_path(relative_path)
    path = (root / clean).resolve()
    path.relative_to(root)
    return path


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def ensure_backend_storage_target(session: AsyncSession) -> models.StorageTarget:
    result = await session.execute(
        select(models.StorageTarget).where(
            models.StorageTarget.name == BACKEND_RECORDINGS_STORAGE_NAME
        )
    )
    target = result.scalar_one_or_none()
    root = str(recordings_root())
    if target is None:
        target = models.StorageTarget(
            name=BACKEND_RECORDINGS_STORAGE_NAME,
            root_path=root,
            device_kind="network",
            purpose="recording",
            is_primary_recording=False,
            is_active=True,
            storage_type="local",
        )
        session.add(target)
        await session.flush()
        return target

    target.root_path = root
    target.device_kind = target.device_kind or "network"
    target.purpose = "recording"
    target.is_active = True
    target.storage_type = "local"
    await session.flush()
    return target


async def ensure_video_stream(session: AsyncSession, camera_id: int) -> models.VideoStream:
    result = await session.execute(
        select(models.VideoStream).where(models.VideoStream.camera_id == camera_id).limit(1)
    )
    stream = result.scalar_one_or_none()
    if stream is not None:
        return stream
    stream = models.VideoStream(camera_id=camera_id, enabled=True)
    session.add(stream)
    await session.flush()
    return stream


def _safe_relative_path(value: str) -> str:
    raw = str(value or "").replace("\\", "/")
    parts = [
        _safe_segment(part)
        for part in PurePosixPath(raw).parts
        if part not in {"", ".", "..", "/"}
    ]
    parts = [part for part in parts if part]
    if not parts:
        raise ValueError("Empty recording path")
    return "/".join(parts)


def _safe_segment(value: str) -> str:
    safe = re.sub(r"[^\w._-]+", "_", value.strip(), flags=re.UNICODE)
    safe = safe.strip("._ ")
    return safe[:160]
