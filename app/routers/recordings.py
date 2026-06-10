import os
import hashlib
from datetime import datetime
from pathlib import Path
import re
from typing import List, Optional
import mimetypes
import asyncio
import subprocess
import threading
import time
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
import cv2
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import get_session
from app.dependencies import get_current_user, get_current_user_allow_query
from app.ffmpeg_tools import ffmpeg_bin, ffprobe_bin
from app.permissions import user_camera_permission, check_permission
from app.processor_media import (
    get_processor_by_id,
    get_processor_media_base_url,
    get_processor_media_headers,
    is_processor_effectively_online,
    parse_processor_file_path,
)
from app.recording_storage import (
    backend_recording_path,
    ensure_backend_storage_target,
    recording_local_path,
    safe_recording_relative_path,
    sha256_file,
)
from app.schemas.recordings import (
    LocalRecordingOut,
    RecordingOut,
    RecordingPage,
    RecordingTimeline,
    RecordingTimelineDay,
    RecordingTimelineHour,
)

router = APIRouter(prefix="/recordings", tags=["recordings"])
CACHE_DIR = Path("recordings_cache")
CACHE_DIR.mkdir(exist_ok=True)
STITCH_DIR = CACHE_DIR / "stitches"
STITCH_DIR.mkdir(exist_ok=True)
FINALIZING_FILE_GRACE_SECONDS = 10.0
_SNAPSHOT_SEMAPHORE = asyncio.Semaphore(2)


def _is_recently_modified(path: Path) -> bool:
    try:
        return time.time() - path.stat().st_mtime < FINALIZING_FILE_GRACE_SECONDS
    except OSError:
        return True


def _is_temporary_recording_path(path: Path) -> bool:
    name = path.name.lower()
    return (
        path.name.startswith(".")
        or ".tmp" in name
        or ".upload." in name
        or name.endswith((".part", ".partial"))
    )
_CACHE_LOCKS: dict[int, threading.Lock] = {}
_CACHE_LOCKS_GUARD = threading.Lock()


def _ffmpeg_bin() -> str | None:
    return ffmpeg_bin()


def _ffprobe_bin() -> str | None:
    return ffprobe_bin(_ffmpeg_bin())


def _cache_lock(recording_id: int) -> threading.Lock:
    with _CACHE_LOCKS_GUARD:
        lock = _CACHE_LOCKS.get(recording_id)
        if lock is None:
            lock = threading.Lock()
            _CACHE_LOCKS[recording_id] = lock
        return lock


def _video_codec(path: Path) -> str | None:
    ffprobe_bin = _ffprobe_bin()
    if not ffprobe_bin:
        return None
    try:
        proc = subprocess.run(
            [
                ffprobe_bin,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=nokey=1:noprint_wrappers=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip().lower() or None


def _ensure_h264_cache(recording_id: int, path: Path, mime: str) -> Path | None:
    ffmpeg_bin = _ffmpeg_bin()
    if not ffmpeg_bin:
        return None
    codec = _video_codec(path)
    if mime == "video/mp4" and codec in {None, "h264"}:
        return None
    if mime != "video/avi" and codec not in {"mpeg4", "mjpeg", "msmpeg4v3", "h263", "h263p"}:
        return None

    cached = CACHE_DIR / f"{recording_id}_h264.mp4"
    with _cache_lock(recording_id):
        try:
            if cached.exists() and cached.stat().st_mtime >= path.stat().st_mtime:
                cached_codec = _video_codec(cached)
                if cached_codec in {None, "h264"}:
                    return cached
                cached.unlink(missing_ok=True)
        except Exception:
            try:
                cached.unlink(missing_ok=True)
            except Exception:
                pass

        temp = cached.with_name(f"{cached.stem}.{os.getpid()}.{threading.get_ident()}.tmp.mp4")
        cmd = [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(path),
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-pix_fmt",
            "yuv420p",
            "-an",
            "-movflags",
            "+faststart",
            str(temp),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=180)
        except Exception:
            try:
                temp.unlink(missing_ok=True)
            except Exception:
                pass
            return None
        if proc.returncode != 0 or not temp.exists() or temp.stat().st_size <= 0:
            try:
                temp.unlink(missing_ok=True)
            except Exception:
                pass
            return None
        converted_codec = _video_codec(temp)
        if converted_codec is not None and converted_codec != "h264":
            try:
                temp.unlink(missing_ok=True)
            except Exception:
                pass
            return None
        try:
            temp.replace(cached)
        except Exception:
            try:
                temp.unlink(missing_ok=True)
            except Exception:
                pass
            return None
        return cached


def _proxy_headers(upstream: httpx.Response) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key in ("content-type", "content-length", "accept-ranges", "content-range", "content-disposition"):
        value = upstream.headers.get(key)
        if value:
            headers[key] = value
    return headers


async def _proxy_processor_stream(url: str, headers: dict[str, str], request: Request | None = None) -> StreamingResponse:
    client = httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=120, write=120, pool=120))
    upstream_headers = dict(headers)
    if request is not None:
        range_header = request.headers.get("range") or request.headers.get("Range")
        if range_header:
            upstream_headers["Range"] = range_header

    stream_cm = client.stream("GET", url, headers=upstream_headers)
    try:
        upstream = await stream_cm.__aenter__()
    except httpx.HTTPError as exc:
        await client.aclose()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Processor media server unavailable",
        ) from exc

    async def gen():
        try:
            async for chunk in upstream.aiter_bytes():
                if chunk:
                    yield chunk
        finally:
            await stream_cm.__aexit__(None, None, None)
            await client.aclose()

    return StreamingResponse(
        gen(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
        headers=_proxy_headers(upstream),
    )


async def _proxy_processor_bytes(url: str, headers: dict[str, str]) -> Response:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            upstream = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Processor media server unavailable",
        ) from exc
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
        headers=_proxy_headers(upstream),
    )


async def _resolve_processor_media(
    session: AsyncSession,
    file_path: str,
    camera_id: int | None = None,
) -> tuple[models.Processor, str] | None:
    parsed = parse_processor_file_path(file_path)
    if not parsed:
        return None
    processor_id, relative_path = parsed
    proc = await get_processor_by_id(session, processor_id)
    if proc is not None and proc.ip_address and is_processor_effectively_online(proc):
        return proc, relative_path

    # Recordings are stored on the processor machine. If backend/processor were
    # reinstalled and the processor received a new id, keep the archive usable by
    # falling back to the currently assigned online processor for the camera.
    if camera_id is not None:
        fallback_result = await session.execute(
            select(models.Processor)
            .join(
                models.ProcessorCameraAssignment,
                models.ProcessorCameraAssignment.processor_id == models.Processor.processor_id,
            )
            .where(
                models.ProcessorCameraAssignment.camera_id == camera_id,
                models.Processor.status == "online",
            )
            .order_by(models.Processor.last_heartbeat.desc(), models.Processor.processor_id.desc())
        )
        fallback_proc = next(
            (
                item
                for item in fallback_result.scalars().all()
                if item.ip_address and is_processor_effectively_online(item)
            ),
            None,
        )
        if fallback_proc is not None:
            return fallback_proc, relative_path

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Processor not found")


def _processor_media_url(proc: models.Processor, prefix: str, relative_path: str) -> str:
    return f"{get_processor_media_base_url(proc)}{prefix}/{quote(relative_path.lstrip('/'), safe='/')}"


def _media_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "video/mp4"


def _file_response(path: Path, request: Request, media_type: str | None = None, filename: str | None = None):
    mime = media_type or _media_type(path)
    file_size = path.stat().st_size
    range_header = request.headers.get("range") or request.headers.get("Range")
    if range_header:
        m = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else file_size - 1
            end = min(end, file_size - 1)
            if start >= file_size:
                raise HTTPException(
                    status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                    detail="Range not satisfiable",
                )
            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(end - start + 1),
                "Content-Disposition": f'inline; filename="{filename or path.name}"',
            }
            return StreamingResponse(_range_stream(path, start, end), status_code=206, media_type=mime, headers=headers)
    return FileResponse(
        path,
        media_type=mime,
        filename=filename or path.name,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            "Content-Disposition": f'inline; filename="{filename or path.name}"',
        },
    )


def _render_recording_snapshot(
    path: Path,
    ts: float | None,
    max_width: int,
    quality: int,
) -> bytes:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError("Cannot open video")
    try:
        if ts is not None and ts > 0:
            cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000)
        else:
            frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            if ts is None and frames and frames > 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frames / 2)
        ok, frame = cap.read()
        if not ok or frame is None:
            raise RuntimeError("Cannot read frame")
        height, width = frame.shape[:2]
        if width > max_width:
            scale = max_width / float(width)
            frame = cv2.resize(
                frame,
                (max_width, max(1, int(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
        ok, buf = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)],
        )
        if not ok:
            raise RuntimeError("Encode failed")
        return buf.tobytes()
    finally:
        cap.release()


def _concat_file_line(path: Path) -> str:
    safe = str(path.resolve()).replace("\\", "/").replace("'", "\\'")
    return f"file '{safe}'\n"


async def _ensure_backend_recording_file(
    session: AsyncSession,
    recording: models.RecordingFile,
    camera_id: int,
) -> Path:
    local_path = recording_local_path(recording.file_path)
    if local_path is not None:
        return local_path
    file_path = recording.file_path or ""
    if not file_path.startswith("processor://"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File missing")

    processor_media = await _resolve_processor_media(session, file_path, camera_id=camera_id)
    if processor_media is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Processor media not found")
    proc, relative_path = processor_media
    destination = backend_recording_path(
        safe_recording_relative_path(
            camera_id=camera_id,
            started_at=recording.started_at,
            source_path=relative_path,
        )
    )
    if destination.is_file() and destination.stat().st_size > 0:
        await _attach_backend_file(session, recording, destination)
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_name(f".{destination.name}.{recording.recording_file_id}.download")
    url = _processor_media_url(proc, "/media/recordings", relative_path)
    size = 0
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=300, write=120, pool=120)) as client:
            async with client.stream("GET", url, headers=get_processor_media_headers(proc)) as response:
                if response.status_code >= 400:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Processor recording unavailable: {response.status_code}",
                    )
                with temp_path.open("wb") as handle:
                    async for chunk in response.aiter_bytes():
                        if not chunk:
                            continue
                        size += len(chunk)
                        handle.write(chunk)
        if size <= 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Processor returned empty recording")
        temp_path.replace(destination)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Processor media server unavailable",
        ) from exc
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

    await _attach_backend_file(session, recording, destination)
    return destination


async def _attach_backend_file(session: AsyncSession, recording: models.RecordingFile, path: Path) -> None:
    storage_target = await ensure_backend_storage_target(session)
    recording.storage_target_id = storage_target.storage_target_id
    recording.file_path = str(path)
    recording.file_size_bytes = path.stat().st_size
    recording.checksum = await asyncio.to_thread(sha256_file, path)
    await session.commit()


def _recording_out(recording: models.RecordingFile, camera_id: int) -> RecordingOut:
    return RecordingOut(
        recording_file_id=recording.recording_file_id,
        camera_id=camera_id,
        video_stream_id=recording.video_stream_id,
        file_kind=recording.file_kind,
        file_path=recording.file_path,
        started_at=recording.started_at.isoformat(),
        ended_at=recording.ended_at.isoformat() if recording.ended_at else None,
        duration_seconds=float(recording.duration_seconds) if recording.duration_seconds else None,
        file_size_bytes=int(recording.file_size_bytes) if recording.file_size_bytes else None,
        checksum=recording.checksum,
    )


def _apply_recording_filters(
    stmt,
    *,
    camera_id: int | None,
    date_from: str | None,
    date_to: str | None,
):
    if camera_id is not None:
        stmt = stmt.where(models.VideoStream.camera_id == camera_id)
    if date_from:
        try:
            stmt = stmt.where(models.RecordingFile.started_at >= datetime.fromisoformat(date_from))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="date_from must be an ISO datetime") from exc
    if date_to:
        try:
            stmt = stmt.where(models.RecordingFile.started_at <= datetime.fromisoformat(date_to))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="date_to must be an ISO datetime") from exc
    return stmt


@router.get("", response_model=List[RecordingOut])
async def list_recordings(
    camera_id: Optional[int] = Query(default=None),
    date_from: Optional[str] = Query(default=None, description="ISO datetime start"),
    date_to: Optional[str] = Query(default=None, description="ISO datetime end"),
    limit: int = Query(default=300, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> List[RecordingOut]:
    stmt = (
        select(models.RecordingFile, models.VideoStream.camera_id)
        .join(models.VideoStream, models.VideoStream.video_stream_id == models.RecordingFile.video_stream_id)
        .order_by(models.RecordingFile.started_at.desc())
        .offset(offset)
        .limit(limit)
    )
    stmt = _apply_recording_filters(
        stmt,
        camera_id=camera_id,
        date_from=date_from,
        date_to=date_to,
    )

    res = await session.execute(stmt)
    rows = res.all()

    output: List[RecordingOut] = []
    for recording, cam_id in rows:
        perm = await user_camera_permission(session, current_user.user_id, cam_id)
        if not check_permission(perm, "view") and current_user.role_id != 1:
            continue
        output.append(_recording_out(recording, cam_id))

    return output


@router.get("/page", response_model=RecordingPage)
async def paged_recordings(
    camera_id: Optional[int] = Query(default=None),
    date_from: Optional[str] = Query(default=None, description="ISO datetime start"),
    date_to: Optional[str] = Query(default=None, description="ISO datetime end"),
    limit: int = Query(default=60, ge=1, le=240),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> RecordingPage:
    base = (
        select(models.RecordingFile, models.VideoStream.camera_id)
        .join(models.VideoStream, models.VideoStream.video_stream_id == models.RecordingFile.video_stream_id)
        .where(models.RecordingFile.file_kind == "video")
    )
    base = _apply_recording_filters(
        base,
        camera_id=camera_id,
        date_from=date_from,
        date_to=date_to,
    )
    count_stmt = _apply_recording_filters(
        select(func.count(models.RecordingFile.recording_file_id))
        .join(models.VideoStream, models.VideoStream.video_stream_id == models.RecordingFile.video_stream_id)
        .where(models.RecordingFile.file_kind == "video"),
        camera_id=camera_id,
        date_from=date_from,
        date_to=date_to,
    )
    total = int((await session.execute(count_stmt)).scalar_one())
    rows = (
        await session.execute(
            base.order_by(models.RecordingFile.started_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    items: list[RecordingOut] = []
    for recording, cam_id in rows:
        permission = await user_camera_permission(session, current_user.user_id, cam_id)
        if check_permission(permission, "view") or current_user.role_id == 1:
            items.append(_recording_out(recording, cam_id))
    return RecordingPage(total=total, limit=limit, offset=offset, items=items)


@router.get("/timeline", response_model=RecordingTimeline)
async def recording_timeline(
    camera_id: Optional[int] = Query(default=None),
    date_from: Optional[str] = Query(default=None, description="ISO datetime start"),
    date_to: Optional[str] = Query(default=None, description="ISO datetime end"),
    day_limit: int = Query(default=31, ge=1, le=366),
    day_offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> RecordingTimeline:
    del current_user  # All authenticated roles have view access to cameras.
    day_bucket = func.date_trunc("day", models.RecordingFile.started_at)
    hour_bucket = func.date_trunc("hour", models.RecordingFile.started_at)
    base_filters = (
        models.RecordingFile.file_kind == "video",
    )

    day_stmt = (
        select(
            day_bucket.label("bucket"),
            func.count(models.RecordingFile.recording_file_id).label("clip_count"),
            func.coalesce(func.sum(models.RecordingFile.duration_seconds), 0).label("duration_seconds"),
            func.coalesce(func.sum(models.RecordingFile.file_size_bytes), 0).label("size_bytes"),
        )
        .join(models.VideoStream, models.VideoStream.video_stream_id == models.RecordingFile.video_stream_id)
        .where(*base_filters)
        .group_by(day_bucket)
        .order_by(day_bucket.desc())
    )
    day_stmt = _apply_recording_filters(
        day_stmt,
        camera_id=camera_id,
        date_from=date_from,
        date_to=date_to,
    )
    count_days_stmt = (
        select(
            func.count(func.distinct(day_bucket)),
            func.count(models.RecordingFile.recording_file_id),
        )
        .join(models.VideoStream, models.VideoStream.video_stream_id == models.RecordingFile.video_stream_id)
        .where(*base_filters)
    )
    count_days_stmt = _apply_recording_filters(
        count_days_stmt,
        camera_id=camera_id,
        date_from=date_from,
        date_to=date_to,
    )
    total_days, total_clips = (await session.execute(count_days_stmt)).one()
    day_rows = (
        await session.execute(day_stmt.offset(day_offset).limit(day_limit))
    ).all()
    selected_days = [row.bucket for row in day_rows]
    if not selected_days:
        return RecordingTimeline(
            total_days=int(total_days or 0),
            total_clips=int(total_clips or 0),
            day_limit=day_limit,
            day_offset=day_offset,
            days=[],
        )

    hour_stmt = (
        select(
            day_bucket.label("day_bucket"),
            hour_bucket.label("hour_bucket"),
            func.count(models.RecordingFile.recording_file_id).label("clip_count"),
            func.coalesce(func.sum(models.RecordingFile.duration_seconds), 0).label("duration_seconds"),
            func.coalesce(func.sum(models.RecordingFile.file_size_bytes), 0).label("size_bytes"),
            func.min(models.RecordingFile.started_at).label("first_at"),
            func.max(models.RecordingFile.started_at).label("last_at"),
            func.max(models.RecordingFile.recording_file_id).label("preview_recording_id"),
        )
        .join(models.VideoStream, models.VideoStream.video_stream_id == models.RecordingFile.video_stream_id)
        .where(*base_filters, day_bucket.in_(selected_days))
        .group_by(day_bucket, hour_bucket)
        .order_by(day_bucket.desc(), hour_bucket.desc())
    )
    hour_stmt = _apply_recording_filters(
        hour_stmt,
        camera_id=camera_id,
        date_from=date_from,
        date_to=date_to,
    )
    hours_by_day: dict[datetime, list[RecordingTimelineHour]] = {}
    for row in (await session.execute(hour_stmt)).all():
        hours_by_day.setdefault(row.day_bucket, []).append(
            RecordingTimelineHour(
                hour=row.hour_bucket.hour,
                clip_count=int(row.clip_count),
                duration_seconds=float(row.duration_seconds or 0),
                size_bytes=int(row.size_bytes or 0),
                first_at=row.first_at.isoformat(),
                last_at=row.last_at.isoformat(),
                preview_recording_id=int(row.preview_recording_id),
            )
        )

    days = [
        RecordingTimelineDay(
            date=row.bucket.date().isoformat(),
            clip_count=int(row.clip_count),
            duration_seconds=float(row.duration_seconds or 0),
            size_bytes=int(row.size_bytes or 0),
            hours=hours_by_day.get(row.bucket, []),
        )
        for row in day_rows
    ]
    return RecordingTimeline(
        total_days=int(total_days or 0),
        total_clips=int(total_clips or 0),
        day_limit=day_limit,
        day_offset=day_offset,
        days=days,
    )


@router.get("/files", response_model=List[LocalRecordingOut])
async def list_local_recordings(
    current_user: models.User = Depends(get_current_user),
    camera_id: Optional[int] = Query(default=None),
) -> List[LocalRecordingOut]:
    """
    List video files from local recordings directory (recordings/).
    This is filesystem-only (detector output), not DB-linked.
    """
    base = Path("recordings")
    if not base.exists():
        return []

    items: List[LocalRecordingOut] = []
    for entry in sorted(base.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
        if _is_temporary_recording_path(entry):
            continue
        if _is_recently_modified(entry):
            continue
        stat = entry.stat()
        rel = entry.relative_to(base).as_posix()
        cam_id: Optional[int] = None
        m = re.search(r"(?:cam|camera_)(\d+)", rel)
        if m:
            try:
                cam_id = int(m.group(1))
            except ValueError:
                cam_id = None
        if camera_id and cam_id and cam_id != camera_id:
            continue
        items.append(
            LocalRecordingOut(
                name=rel,
                url=f"/recordings/local/{quote(rel, safe='/')}",
                size_bytes=stat.st_size,
                modified_at=str(
                    __import__("datetime").datetime.fromtimestamp(stat.st_mtime)
                ),
                camera_id=cam_id,
            )
        )
    return items


@router.get("/local/{filename:path}")
async def download_local_recording(
    filename: str,
    request: Request,
    current_user: models.User = Depends(get_current_user_allow_query),
):
    base = Path("recordings").resolve()
    path = (base / filename).resolve()
    try:
        path.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
    if _is_temporary_recording_path(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
    if _is_recently_modified(path):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Recording file is still being finalized",
        )

    mime, _ = mimetypes.guess_type(path.name)
    if not mime:
        mime = "video/mp4"
    file_size = path.stat().st_size
    range_header = request.headers.get("range") or request.headers.get("Range")
    if range_header:
        m = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else file_size - 1
            end = min(end, file_size - 1)
            if start >= file_size:
                raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE, detail="Range not satisfiable")
            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(end - start + 1),
                "Content-Disposition": f'inline; filename="{path.name}"',
            }
            return StreamingResponse(_range_stream(path, start, end), status_code=206, media_type=mime, headers=headers)
    return FileResponse(
        path,
        media_type=mime,
        filename=path.name,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            "Content-Disposition": f'inline; filename="{path.name}"',
        },
    )


def _range_stream(path: Path, start: int, end: int, chunk_size: int = 1024 * 1024):
    with path.open("rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = f.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/stitch")
async def stitch_recordings(
    request: Request,
    ids: Optional[str] = Query(default=None, description="Comma-separated recording_file_id list"),
    camera_id: Optional[int] = Query(default=None),
    date_from: Optional[str] = Query(default=None, description="ISO datetime start"),
    date_to: Optional[str] = Query(default=None, description="ISO datetime end"),
    limit: int = Query(default=720, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user_allow_query),
):
    ffmpeg_bin = _ffmpeg_bin()
    if not ffmpeg_bin:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ffmpeg is not available")

    requested_ids: list[int] = []
    if ids:
        try:
            requested_ids = [int(item.strip()) for item in ids.split(",") if item.strip()]
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid recording ids")
    if not requested_ids and camera_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="camera_id or ids is required")

    stmt = (
        select(models.RecordingFile, models.VideoStream.camera_id)
        .join(models.VideoStream, models.VideoStream.video_stream_id == models.RecordingFile.video_stream_id)
        .where(models.RecordingFile.file_kind == "video")
        .order_by(models.RecordingFile.started_at.asc(), models.RecordingFile.recording_file_id.asc())
        .limit(limit)
    )
    if requested_ids:
        stmt = stmt.where(models.RecordingFile.recording_file_id.in_(requested_ids))
    if camera_id:
        stmt = stmt.where(models.VideoStream.camera_id == camera_id)
    if date_from:
        try:
            stmt = stmt.where(models.RecordingFile.started_at >= datetime.fromisoformat(date_from))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid date_from")
    if date_to:
        try:
            stmt = stmt.where(models.RecordingFile.started_at <= datetime.fromisoformat(date_to))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid date_to")

    result = await session.execute(stmt)
    rows = result.all()
    if requested_ids:
        order = {recording_id: index for index, recording_id in enumerate(requested_ids)}
        rows = sorted(rows, key=lambda row: order.get(row[0].recording_file_id, len(order)))

    paths: list[Path] = []
    for recording, cam_id in rows:
        perm = await user_camera_permission(session, current_user.user_id, cam_id)
        if not check_permission(perm, "view") and current_user.role_id != 1:
            continue
        paths.append(await _ensure_backend_recording_file(session, recording, cam_id))

    if not paths:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No recordings to stitch")
    if len(paths) == 1:
        return _file_response(paths[0], request)

    key_material = "|".join(
        f"{path}:{path.stat().st_mtime_ns}:{path.stat().st_size}" for path in paths
    )
    cache_key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:32]
    list_path = STITCH_DIR / f"{cache_key}.txt"
    output_path = STITCH_DIR / f"{cache_key}.mp4"

    if not output_path.is_file() or output_path.stat().st_size <= 0:
        list_path.write_text("".join(_concat_file_line(path) for path in paths), encoding="utf-8")
        copy_cmd = [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        proc = await asyncio.to_thread(subprocess.run, copy_cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not output_path.is_file() or output_path.stat().st_size <= 0:
            transcode_cmd = [
                ffmpeg_bin,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-vf",
                "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
                "-an",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
            proc = await asyncio.to_thread(subprocess.run, transcode_cmd, capture_output=True, text=True)
            if proc.returncode != 0 or not output_path.is_file() or output_path.stat().st_size <= 0:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Failed to stitch recordings: {proc.stderr[-500:]}",
                )

    return _file_response(output_path, request, media_type="video/mp4", filename=f"recordings_{cache_key}.mp4")


@router.get("/file/{recording_id}")
async def download_recording(
    recording_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user_allow_query),
):
    res = await session.execute(
        select(models.RecordingFile, models.VideoStream.camera_id)
        .join(models.VideoStream, models.VideoStream.video_stream_id == models.RecordingFile.video_stream_id)
        .where(models.RecordingFile.recording_file_id == recording_id)
    )
    row = res.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
    recording, cam_id = row
    perm = await user_camera_permission(session, current_user.user_id, cam_id)
    if not check_permission(perm, "view") and current_user.role_id != 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    local_path = recording_local_path(recording.file_path)
    if local_path is None and str(recording.file_path or "").startswith("processor://"):
        processor_media = await _resolve_processor_media(session, recording.file_path or "", camera_id=cam_id)
        if processor_media is not None:
            proc, relative_path = processor_media
            url = _processor_media_url(proc, "/media/recordings", relative_path)
            return await _proxy_processor_stream(url, get_processor_media_headers(proc), request)

    path = local_path or await _ensure_backend_recording_file(session, recording, cam_id)

    mime = _media_type(path)
    force_compat = str(request.query_params.get("compat") or "").lower() in {"1", "true", "yes"}
    if force_compat or mime != "video/mp4":
        compatible = await asyncio.to_thread(
            _ensure_h264_cache,
            recording.recording_file_id,
            path,
            mime,
        )
        if compatible is not None:
            path = compatible
            mime = "video/mp4"

    # If AVI/MJPG: transcode to MP4 with ffmpeg once and cache
    ffmpeg_bin = _ffmpeg_bin()
    if mime == "video/avi" and ffmpeg_bin:
        cached = CACHE_DIR / f"{recording.recording_file_id}.mp4"
        need_build = True
        if cached.exists():
            try:
                if cached.stat().st_mtime >= path.stat().st_mtime:
                    need_build = False
            except Exception:
                need_build = True
        if need_build:
            cmd = [
                ffmpeg_bin,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(path),
                "-vf",
                "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-tune",
                "zerolatency",
                "-pix_fmt",
                "yuv420p",
                "-an",
                "-movflags",
                "+faststart",
                str(cached),
            ]
            proc = subprocess.run(cmd, capture_output=True)
            if proc.returncode != 0 or not cached.exists():
                # fall back to MJPEG streaming below
                cached = None
        if cached and cached.exists():
            path = cached
            mime = "video/mp4"

    # if avi/mjpg — transcode to mp4 via ffmpeg (no Range support here)
    if mime == "video/avi" and ffmpeg_bin:
        async def _transcode():
            cmd = [
                ffmpeg_bin,
                "-hide_banner",
                "-loglevel", "error",
                "-i", str(path),
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-tune", "zerolatency",
                "-pix_fmt", "yuv420p",
                "-an",
                "-movflags", "+faststart",
                "-f", "mp4",
                "pipe:1",
            ]
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE)
            try:
                while True:
                    chunk = await proc.stdout.read(1024 * 64)
                    if not chunk:
                        break
                    yield chunk
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()

        return StreamingResponse(_transcode(), media_type="video/mp4")

    return _file_response(path, request, media_type=mime)


@router.get("/file/{recording_id}/mjpeg")
async def stream_recording_mjpeg(
    recording_id: int,
    fps: float | None = Query(default=None, ge=1, le=30, description="Кадров в секунду"),
    max_width: int = Query(default=960, ge=320, le=1920, description="Максимальная ширина кадра"),
    quality: int = Query(default=72, ge=40, le=95, description="JPEG quality"),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user_allow_query),
):
    res = await session.execute(
        select(models.RecordingFile, models.VideoStream.camera_id)
        .join(models.VideoStream, models.VideoStream.video_stream_id == models.RecordingFile.video_stream_id)
        .where(models.RecordingFile.recording_file_id == recording_id)
    )
    row = res.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
    recording, cam_id = row
    perm = await user_camera_permission(session, current_user.user_id, cam_id)
    if not check_permission(perm, "view") and current_user.role_id != 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    local_path = recording_local_path(recording.file_path)
    if local_path is None and str(recording.file_path or "").startswith("processor://"):
        processor_media = await _resolve_processor_media(session, recording.file_path or "", camera_id=cam_id)
        if processor_media is not None:
            proc, relative_path = processor_media
            query = urlencode(
                {
                    "fps": f"{float(fps or 8.0):g}",
                    "max_width": str(max_width),
                    "quality": str(quality),
                }
            )
            url = f"{_processor_media_url(proc, '/media/recordings-mjpeg', relative_path)}?{query}"
            return await _proxy_processor_stream(url, get_processor_media_headers(proc))

    path = local_path or await _ensure_backend_recording_file(session, recording, cam_id)

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Cannot open video")
    try:
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 10.0
        target_fps = min(float(fps or 8.0), float(src_fps or 8.0), 15.0)
        delay = 1.0 / max(target_fps, 1.0)
        frame_step = max(1, round(float(src_fps or target_fps) / target_fps))
        encode_opts = [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]

        async def gen():
            frame_index = 0
            try:
                while True:
                    ok, frame = await asyncio.to_thread(cap.read)
                    if not ok or frame is None:
                        break
                    frame_index += 1
                    if frame_step > 1 and frame_index % frame_step != 1:
                        continue
                    height, width = frame.shape[:2]
                    if width > max_width:
                        scale = max_width / float(width)
                        frame = cv2.resize(
                            frame,
                            (max_width, max(1, int(height * scale))),
                            interpolation=cv2.INTER_AREA,
                        )
                    ok, buf = cv2.imencode(".jpg", frame, encode_opts)
                    if not ok:
                        continue
                    chunk = buf.tobytes()
                    header = (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        + f"Content-Length: {len(chunk)}\r\n\r\n".encode("ascii")
                    )
                    yield header + chunk + b"\r\n"
                    await asyncio.sleep(delay)
            finally:
                cap.release()

        return StreamingResponse(
            gen(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
        )
    except Exception:
        cap.release()
        raise


@router.get("/snapshot/{recording_id}")
async def snapshot_recording(
    recording_id: int,
    ts: float | None = Query(default=None, description="Timestamp in seconds"),
    max_width: int = Query(default=640, ge=160, le=1920, description="Максимальная ширина кадра"),
    quality: int = Query(default=72, ge=40, le=95, description="JPEG quality"),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user_allow_query),
):
    res = await session.execute(
        select(models.RecordingFile, models.VideoStream.camera_id)
        .join(models.VideoStream, models.VideoStream.video_stream_id == models.RecordingFile.video_stream_id)
        .where(models.RecordingFile.recording_file_id == recording_id)
    )
    row = res.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
    recording, cam_id = row
    perm = await user_camera_permission(session, current_user.user_id, cam_id)
    if not check_permission(perm, "view") and current_user.role_id != 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    local_path = recording_local_path(recording.file_path)
    if local_path is None and str(recording.file_path or "").startswith("processor://"):
        processor_media = await _resolve_processor_media(session, recording.file_path or "", camera_id=cam_id)
        if processor_media is not None:
            proc, relative_path = processor_media
            query_items = {"max_width": str(max_width), "quality": str(quality)}
            if ts is not None:
                query_items["ts"] = f"{ts:g}"
            query = urlencode(query_items)
            url = _processor_media_url(proc, "/media/recordings-snapshot", relative_path)
            url = f"{url}?{query}"
            async with _SNAPSHOT_SEMAPHORE:
                return await _proxy_processor_bytes(
                    url,
                    get_processor_media_headers(proc),
                )

    path = local_path or await _ensure_backend_recording_file(session, recording, cam_id)
    try:
        async with _SNAPSHOT_SEMAPHORE:
            snapshot = await asyncio.to_thread(
                _render_recording_snapshot,
                path,
                ts,
                max_width,
                quality,
            )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return Response(content=snapshot, media_type="image/jpeg")
