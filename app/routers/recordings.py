import os
from datetime import datetime
from pathlib import Path
import re
from typing import List, Optional
import mimetypes
import asyncio
import shutil
import subprocess
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
import cv2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import get_session
from app.dependencies import get_current_user, get_current_user_allow_query
from app.permissions import user_camera_permission, check_permission
from app.processor_media import (
    get_processor_by_id,
    get_processor_media_base_url,
    get_processor_media_headers,
    parse_processor_file_path,
)
from app.schemas.recordings import RecordingOut, LocalRecordingOut

router = APIRouter(prefix="/recordings", tags=["recordings"])
FFMPEG_BIN = os.environ.get("FFMPEG_BIN") or shutil.which("ffmpeg") or r"C:\ffmpeg-essentials\ffmpeg.exe"
CACHE_DIR = Path("recordings_cache")
CACHE_DIR.mkdir(exist_ok=True)


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
    upstream = await stream_cm.__aenter__()

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
    async with httpx.AsyncClient(timeout=30) as client:
        upstream = await client.get(url, headers=headers)
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
    if proc is not None and proc.ip_address:
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
            .limit(1)
        )
        fallback_proc = fallback_result.scalar_one_or_none()
        if fallback_proc is not None and fallback_proc.ip_address:
            return fallback_proc, relative_path

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Processor not found")


def _processor_media_url(proc: models.Processor, prefix: str, relative_path: str) -> str:
    return f"{get_processor_media_base_url(proc)}{prefix}/{quote(relative_path.lstrip('/'), safe='/')}"


@router.get("", response_model=List[RecordingOut])
async def list_recordings(
    camera_id: Optional[int] = Query(default=None),
    date_from: Optional[str] = Query(default=None, description="ISO datetime start"),
    date_to: Optional[str] = Query(default=None, description="ISO datetime end"),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> List[RecordingOut]:
    stmt = (
        select(models.RecordingFile, models.VideoStream.camera_id)
        .join(models.VideoStream, models.VideoStream.video_stream_id == models.RecordingFile.video_stream_id)
        .order_by(models.RecordingFile.started_at.desc())
        .limit(limit)
    )
    if camera_id:
        stmt = stmt.where(models.VideoStream.camera_id == camera_id)
    if date_from:
        try:
            stmt = stmt.where(models.RecordingFile.started_at >= datetime.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            stmt = stmt.where(models.RecordingFile.started_at <= datetime.fromisoformat(date_to))
        except ValueError:
            pass

    res = await session.execute(stmt)
    rows = res.all()

    output: List[RecordingOut] = []
    for recording, cam_id in rows:
        perm = await user_camera_permission(session, current_user.user_id, cam_id)
        if not check_permission(perm, "view") and current_user.role_id != 1:
            continue
        output.append(
            RecordingOut(
                recording_file_id=recording.recording_file_id,
                camera_id=cam_id,
                video_stream_id=recording.video_stream_id,
                file_kind=recording.file_kind,
                file_path=recording.file_path,
                started_at=recording.started_at.isoformat(),
                ended_at=recording.ended_at.isoformat() if recording.ended_at else None,
                duration_seconds=float(recording.duration_seconds) if recording.duration_seconds else None,
                file_size_bytes=int(recording.file_size_bytes) if recording.file_size_bytes else None,
                checksum=recording.checksum,
            )
        )

    return output


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
    for entry in sorted(base.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = entry.stat()
        cam_id: Optional[int] = None
        m = re.search(r"cam(\\d+)", entry.name)
        if m:
            try:
                cam_id = int(m.group(1))
            except ValueError:
                cam_id = None
        if camera_id and cam_id and cam_id != camera_id:
            continue
        items.append(
            LocalRecordingOut(
                name=entry.name,
                url=f"/recordings/static/{entry.name}",
                size_bytes=stat.st_size,
                modified_at=str(
                    __import__("datetime").datetime.fromtimestamp(stat.st_mtime)
                ),
                camera_id=cam_id,
            )
        )
    return items


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
    processor_media = await _resolve_processor_media(session, recording.file_path, camera_id=cam_id)
    if processor_media is not None:
        proc, relative_path = processor_media
        return await _proxy_processor_stream(
            _processor_media_url(proc, "/media/recordings", relative_path),
            get_processor_media_headers(proc),
            request=request,
        )
    path = Path(recording.file_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File missing")

    mime, _ = mimetypes.guess_type(path.name)
    if not mime:
        mime = "video/mp4"

    # If AVI/MJPG: transcode to MP4 with ffmpeg once and cache
    if mime == "video/avi" and FFMPEG_BIN:
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
                FFMPEG_BIN,
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

    file_size = path.stat().st_size

    # if avi/mjpg — transcode to mp4 via ffmpeg (no Range support here)
    if mime == "video/avi" and FFMPEG_BIN:
        async def _transcode():
            cmd = [
                FFMPEG_BIN,
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
            }
            return StreamingResponse(_range_stream(path, start, end), status_code=206, media_type=mime, headers=headers)
    return FileResponse(
        path,
        media_type=mime,
        filename=path.name,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            # Safari иногда требует Content-Disposition для inline
            "Content-Disposition": f'inline; filename="{path.name}"',
        },
    )


@router.get("/file/{recording_id}/mjpeg")
async def stream_recording_mjpeg(
    recording_id: int,
    fps: float | None = Query(default=None, ge=1, le=30, description="Кадров в секунду (по умолчанию из файла)"),
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
    processor_media = await _resolve_processor_media(session, recording.file_path, camera_id=cam_id)
    if processor_media is not None:
        proc, relative_path = processor_media
        return await _proxy_processor_stream(
            _processor_media_url(proc, "/media/recordings-mjpeg", relative_path),
            get_processor_media_headers(proc),
        )
    path = Path(recording.file_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File missing")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Cannot open video")
    try:
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 10.0
        delay = 1.0 / (fps or src_fps or 10.0)

        async def gen():
            try:
                while True:
                    ok, frame = await asyncio.to_thread(cap.read)
                    if not ok or frame is None:
                        break
                    ok, buf = cv2.imencode(".jpg", frame)
                    if not ok:
                        continue
                    chunk = buf.tobytes()
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + chunk + b"\r\n"
                    await asyncio.sleep(delay)
            finally:
                cap.release()

        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")
    except Exception:
        cap.release()
        raise


@router.get("/snapshot/{recording_id}")
async def snapshot_recording(
    recording_id: int,
    ts: float | None = Query(default=None, description="Timestamp in seconds"),
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
    processor_media = await _resolve_processor_media(session, recording.file_path, camera_id=cam_id)
    if processor_media is not None:
        proc, relative_path = processor_media
        url = _processor_media_url(proc, "/media/recordings-snapshot", relative_path)
        if ts is not None:
            url = f"{url}?ts={ts}"
        return await _proxy_processor_bytes(url, get_processor_media_headers(proc))
    path = Path(recording.file_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File missing")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Cannot open video")
    try:
        if ts is not None:
            cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000)
        else:
            frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            if frames and frames > 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frames / 2)
        ok, frame = cap.read()
        if not ok or frame is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Cannot read frame")
        ok, buf = cv2.imencode(".jpg", frame)
        if not ok:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Encode failed")
        return Response(content=buf.tobytes(), media_type="image/jpeg")
    finally:
        cap.release()
